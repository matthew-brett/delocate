"""Direct tests of fixes to wheels."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import zipfile
from glob import glob
from os.path import abspath, basename, exists, isdir, realpath
from os.path import join as pjoin
from pathlib import Path
from subprocess import check_call
from typing import NamedTuple

import pytest

from ..delocating import (
    DLC_PREFIX,
    delocate_wheel,
    patch_wheel,
)
from ..libsana import DelocationError
from ..tmpdirs import InGivenDirectory, InTemporaryDirectory
from ..tools import (
    dir2zip,
    get_archs,
    get_install_id,
    get_install_names,
    set_install_name,
    zip2dir,
)
from ..wheeltools import InWheel
from .env_tools import _scope_env
from .pytest_tools import assert_equal, assert_false, assert_true
from .test_install_names import DATA_PATH, EXT_LIBS
from .test_tools import ARCH_BOTH, ARCH_M1


def _collect_wheel(globber):
    glob_path = pjoin(DATA_PATH, globber)
    wheels = glob(glob_path)
    if len(wheels) == 0:
        raise ValueError(f"No wheels for glob {glob_path}")
    elif len(wheels) > 1:
        raise ValueError(
            "Too many wheels for glob {} ({})".format(
                glob_path, "; ".join(wheels)
            )
        )
    return wheels[0]


PLAT_WHEEL = _collect_wheel("fakepkg1-1.0-cp*.whl")
PURE_WHEEL = _collect_wheel("fakepkg2-1.0-py*.whl")
RPATH_WHEEL = _collect_wheel("fakepkg_rpath-1.0-cp*.whl")
TOPLEVEL_WHEEL = _collect_wheel("fakepkg_toplevel-1.0-cp*.whl")
NAMESPACE_WHEEL = _collect_wheel("fakepkg_namespace-1.0-cp*.whl")
STRAY_LIB = pjoin(DATA_PATH, "libextfunc.dylib")
# The install_name in the wheel for the stray library
STRAY_LIB_DEP = realpath(STRAY_LIB)
WHEEL_PATCH = pjoin(DATA_PATH, "fakepkg2.patch")
WHEEL_PATCH_BAD = pjoin(DATA_PATH, "fakepkg2.bad_patch")


class PlatWheel(NamedTuple):
    """Information about a temporary platform wheel."""

    whl: str  # Path to the wheel.
    stray_lib: str  # Path to the external library.


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_pure_python():
    # Test fixing a pure python package gives no change
    with InTemporaryDirectory():
        os.makedirs("wheels")
        shutil.copy2(PURE_WHEEL, "wheels")
        wheel_name = pjoin("wheels", basename(PURE_WHEEL))
        assert_equal(delocate_wheel(wheel_name), {})
        zip2dir(wheel_name, "pure_pkg")
        assert_true(exists(pjoin("pure_pkg", "fakepkg2")))
        assert_false(exists(pjoin("pure_pkg", "fakepkg2", ".dylibs")))


def _fixed_wheel(out_path: str | Path) -> tuple[str, str]:
    wheel_base = basename(PLAT_WHEEL)
    with InGivenDirectory(out_path):
        zip2dir(PLAT_WHEEL, "_plat_pkg")
        if not exists("_libs"):
            os.makedirs("_libs")
        shutil.copy2(STRAY_LIB, "_libs")
        stray_lib = pjoin(abspath(realpath("_libs")), basename(STRAY_LIB))
        requiring = pjoin("_plat_pkg", "fakepkg1", "subpkg", "module2.abi3.so")
        old_lib = set(get_install_names(requiring)).difference(EXT_LIBS).pop()
        set_install_name(requiring, old_lib, stray_lib)
        dir2zip("_plat_pkg", wheel_base)
        shutil.rmtree("_plat_pkg")
    return pjoin(out_path, wheel_base), stray_lib


def _rename_module(
    in_wheel: str | Path, mod_fname: str | Path, out_wheel: str | Path
) -> None:
    """Rename a module with library dependency in a wheel."""
    with InWheel(str(in_wheel), str(out_wheel)):
        mod_dir = Path("fakepkg1", "subpkg")
        os.rename(Path(mod_dir, "module2.abi3.so"), Path(mod_dir, mod_fname))


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_plat() -> None:
    # Can we fix a wheel with a stray library?
    # We have to make one that works first
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert exists(stray_lib)
        # Shortcut
        _rp = realpath
        # In-place fix
        dep_mod = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
        assert delocate_wheel(fixed_wheel) == {
            _rp(stray_lib): {dep_mod: stray_lib}
        }
        zip2dir(fixed_wheel, "plat_pkg")
        assert exists(pjoin("plat_pkg", "fakepkg1"))
        dylibs = pjoin("plat_pkg", "fakepkg1", ".dylibs")
        assert exists(dylibs)
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        # New output name
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert delocate_wheel(
            fixed_wheel, "fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl"
        ) == {_rp(stray_lib): {dep_mod: stray_lib}}
        zip2dir("fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl", "plat_pkg1")
        assert exists(pjoin("plat_pkg1", "fakepkg1"))
        dylibs = pjoin("plat_pkg1", "fakepkg1", ".dylibs")
        assert exists(dylibs)
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        # Test another lib output directory
        assert delocate_wheel(
            fixed_wheel,
            "fixed_wheel2-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
            "dylibs_dir",
        ) == {_rp(stray_lib): {dep_mod: stray_lib}}
        zip2dir(
            "fixed_wheel2-1.0-cp39-cp39-macosx_10_9_x86_64.whl", "plat_pkg2"
        )
        assert exists(pjoin("plat_pkg2", "fakepkg1"))
        dylibs = pjoin("plat_pkg2", "fakepkg1", "dylibs_dir")
        assert exists(dylibs)
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        # Test check for existing output directory
        with pytest.raises(
            DelocationError,
            match=r".*wheel/fakepkg1/subpkg "
            r"already exists in wheel but need to copy "
            r".*libextfunc.dylib",
        ):
            delocate_wheel(fixed_wheel, "broken_wheel.ext", "subpkg")
        # Test that `wheel unpack` works
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert delocate_wheel(fixed_wheel) == {
            _rp(stray_lib): {dep_mod: stray_lib}
        }
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", fixed_wheel], check=True
        )
        # Check that copied libraries have modified install_name_ids
        zip2dir(fixed_wheel, "plat_pkg3")
        base_stray = basename(stray_lib)
        the_lib = pjoin("plat_pkg3", "fakepkg1", ".dylibs", base_stray)
        inst_id = DLC_PREFIX + "fakepkg1/.dylibs/" + base_stray
        assert get_install_id(the_lib) == inst_id


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_script_permissions():
    with InTemporaryDirectory():
        os.makedirs("wheels")
        wheel_name, stray_lib = _fixed_wheel("wheels")
        whl_name = basename(wheel_name)
        wheel_name = pjoin("wheels", whl_name)
        script_name = pjoin("fakepkg1-1.0.data", "scripts", "fakescript.py")
        exe_name = pjoin("fakepkg1", "ascript")
        lib_path = pjoin("fakepkg1", ".dylibs")
        mtimes = {}
        with InWheel(wheel_name):
            assert not isdir(lib_path)
            for path in (script_name, exe_name):
                st = os.stat(path)
                assert st.st_mode & stat.S_IXUSR
                assert st.st_mode & stat.S_IFREG
                mtimes[path] = st.st_mtime
        os.makedirs("fixed-wheels")
        out_whl = pjoin("fixed-wheels", whl_name)
        delocate_wheel(wheel_name, out_wheel=out_whl)
        with InWheel(out_whl):
            assert isdir(lib_path)
            for path in (script_name, exe_name):
                st = os.stat(path)
                assert st.st_mode & stat.S_IXUSR
                assert st.st_mode & stat.S_IFREG
                # Check modification time is the same as the original
                assert st.st_mtime == mtimes[path]


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_plat_dylibs():
    # Check default and non-default searches for dylibs
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(
            fixed_wheel,
            "module.other",
            "fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
        )
        # With dylibs-only - only analyze files with exts '.dylib', '.so'
        assert_equal(
            delocate_wheel(
                "fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
                lib_filt_func="dylibs-only",
            ),
            {},
        )
        # With func that doesn't find the module

        def func(fn):
            return fn.endswith(".so")

        assert_equal(
            delocate_wheel(
                "fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
                lib_filt_func=func,
            ),
            {},
        )
        # Default - looks in every file
        dep_mod = pjoin("fakepkg1", "subpkg", "module.other")
        assert_equal(
            delocate_wheel("fixed_wheel-1.0-cp39-cp39-macosx_10_9_x86_64.whl"),
            {realpath(stray_lib): {dep_mod: stray_lib}},
        )


def _thin_lib(stray_lib: str | Path, arch: str) -> None:
    stray_lib = str(stray_lib)
    check_call(["lipo", "-thin", arch, stray_lib, "-output", stray_lib])


def _thin_mod(wheel: str | Path, arch: str) -> None:
    with InWheel(wheel, wheel):
        mod_fname = str(Path("fakepkg1", "subpkg", "module2.abi3.so"))
        check_call(["lipo", "-thin", arch, mod_fname, "-output", mod_fname])


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test__thinning():
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        mod_fname = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
        assert_equal(get_archs(stray_lib), ARCH_BOTH)
        with InWheel(fixed_wheel):
            assert_equal(get_archs(mod_fname), ARCH_BOTH)
        _thin_lib(stray_lib, "arm64")
        _thin_mod(fixed_wheel, "arm64")
        assert_equal(get_archs(stray_lib), ARCH_M1)
        with InWheel(fixed_wheel):
            assert_equal(get_archs(mod_fname), ARCH_M1)


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
@pytest.mark.filterwarnings("ignore:The check_verbose flag is deprecated")
def test_check_plat_archs():
    # Check flag to check architectures
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        dep_mod = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
        # No complaint for stored / fixed wheel
        assert_equal(
            delocate_wheel(fixed_wheel, require_archs=()),
            {realpath(stray_lib): {dep_mod: stray_lib}},
        )
        # Make a new copy and break it and fix it again

        def _fix_break(arch_):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch_)

        def _fix_break_fix(arch_):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch_)
            _thin_mod(fixed_wheel, arch_)
            new_name = fixed_wheel.replace("universal2", arch_)
            shutil.move(fixed_wheel, new_name)
            return new_name

        for arch in ("x86_64", "arm64"):
            # OK unless we check
            _fix_break(arch)
            assert_equal(
                delocate_wheel(fixed_wheel, require_archs=None),
                {realpath(stray_lib): {dep_mod: stray_lib}},
            )
            # Now we check, and error raised
            _fix_break(arch)
            with pytest.raises(DelocationError, match=r".*(x86_64|arm64)"):
                delocate_wheel(fixed_wheel, require_archs=())
            # We can fix again by thinning the module too
            fixed_wheel2 = _fix_break_fix(arch)
            assert_equal(
                delocate_wheel(fixed_wheel2, require_archs=()),
                {realpath(stray_lib): {dep_mod: stray_lib}},
            )
            # But if we require the arch we don't have, it breaks
            for req_arch in (
                "universal2",
                ARCH_BOTH,
                ARCH_BOTH.difference([arch]),
            ):
                fixed_wheel3 = _fix_break_fix(arch)
                with pytest.raises(DelocationError, match=r".*(x86_64|arm64)"):
                    delocate_wheel(fixed_wheel3, require_archs=req_arch)
        # Can be verbose (we won't check output though)
        _fix_break("x86_64")
        with pytest.raises(
            DelocationError,
            match=r".*missing architectures in wheel\n"
            r"fakepkg1/subpkg/module2.abi3.so needs arch arm64 missing from "
            r".*/libextfunc.dylib",
        ):
            delocate_wheel(fixed_wheel, require_archs=(), check_verbose=True)


def test_patch_wheel() -> None:
    # Check patching of wheel
    with InTemporaryDirectory():
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        patch_wheel(PURE_WHEEL, WHEEL_PATCH, out_fname)
        zip2dir(out_fname, "wheel1")
        with open(pjoin("wheel1", "fakepkg2", "__init__.py")) as fobj:
            assert fobj.read() == 'print("Am in init")\n'
        # Check that wheel unpack works
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", out_fname], check=True
        )
        # Copy the original, check it doesn't have patch
        shutil.copyfile(PURE_WHEEL, "copied.whl")
        zip2dir("copied.whl", "wheel2")
        with open(pjoin("wheel2", "fakepkg2", "__init__.py")) as fobj:
            assert fobj.read() == '"""Fake package."""\n'
        # Overwrite input wheel (the default)
        patch_wheel("copied.whl", WHEEL_PATCH)
        # Patched
        zip2dir("copied.whl", "wheel3")
        with open(pjoin("wheel3", "fakepkg2", "__init__.py")) as fobj:
            assert fobj.read() == 'print("Am in init")\n'
        # Check bad patch raises error
        with pytest.raises(RuntimeError):
            patch_wheel(PURE_WHEEL, WHEEL_PATCH_BAD, "out.whl")


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_rpath():
    # Test wheels which have an @rpath dependency
    # Also verifies the delocated libraries signature
    with InTemporaryDirectory():
        # The module was set to expect its dependency in the libs/ directory
        os.makedirs("libs")
        shutil.copy(pjoin(DATA_PATH, "libextfunc_rpath.dylib"), "libs")
        shutil.copy(pjoin(DATA_PATH, "libextfunc2_rpath.dylib"), "libs")

        with InWheel(RPATH_WHEEL):
            # dep_mod can vary depending the Python version used to build
            # the test wheel
            dep_mod = "fakepkg/subpkg/module2.abi3.so"
        dep_path = "@rpath/libextfunc_rpath.dylib"

        stray_libs = {
            realpath("libs/libextfunc_rpath.dylib"): {dep_mod: dep_path},
            realpath("libs/libextfunc2_rpath.dylib"): {
                realpath(
                    "libs/libextfunc_rpath.dylib"
                ): "@rpath/libextfunc2_rpath.dylib"
            },
        }

        assert (
            delocate_wheel(
                RPATH_WHEEL, "out-1.0-cp39-cp39-macosx_10_9_x86_64.whl"
            )
            == stray_libs
        )

        with InWheel("out-1.0-cp39-cp39-macosx_10_9_x86_64.whl"):
            check_call(
                [
                    "codesign",
                    "--verify",
                    "fakepkg/.dylibs/libextfunc_rpath.dylib",
                ]
            )

        # Now test filters with recursive dependencies.
        def ignore_libextfunc(path: str) -> bool:
            """Ignore libextfunc which will also ignore its dependency and include no files."""  # noqa: E501
            return "libextfunc_rpath.dylib" not in path

        assert (
            delocate_wheel(
                RPATH_WHEEL,
                "tmp-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
                lib_filt_func=ignore_libextfunc,
            )
            == {}
        )

        def ignore_libextfunc2(path: str) -> bool:
            """Ignore libextfunc2.  libextfunc will still be bundled."""
            return "libextfunc2_rpath.dylib" not in path

        # Only the direct dependencies of module2.abi3.so
        stray_libs_only_direct = {
            realpath("libs/libextfunc_rpath.dylib"): {dep_mod: dep_path},
        }

        assert (
            delocate_wheel(
                RPATH_WHEEL,
                "tmp-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
                lib_filt_func=ignore_libextfunc2,
            )
            == stray_libs_only_direct
        )


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_toplevel() -> None:
    # Test wheels which are not organized into packages.

    with InTemporaryDirectory():
        # The module was set to expect its dependency in the libs/ directory
        os.makedirs("libs")
        shutil.copy(pjoin(DATA_PATH, "libextfunc2_rpath.dylib"), "libs")

        dep_mod = "module2.abi3.so"
        dep_path = "@rpath/libextfunc2_rpath.dylib"

        stray_libs = {
            realpath("libs/libextfunc2_rpath.dylib"): {dep_mod: dep_path},
        }

        assert (
            delocate_wheel(
                TOPLEVEL_WHEEL,
                "out-1.0-cp39-cp39-macosx_10_9_x86_64.whl",
                lib_sdir=".suffix_test",
            )
            == stray_libs
        )
        with InWheel("out-1.0-cp39-cp39-macosx_10_9_x86_64.whl") as wheel_path:
            assert "fakepkg_toplevel.suffix_test" in os.listdir(wheel_path)


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_fix_namespace() -> None:
    # Test wheels which are organized with a namespace.
    with InTemporaryDirectory():
        # The module was set to expect its dependency in the libs/ directory
        os.makedirs("libs")
        shutil.copy(pjoin(DATA_PATH, "libextfunc2_rpath.dylib"), "libs")

        dep_mod = "namespace/subpkg/module2.abi3.so"
        dep_path = "@rpath/libextfunc2_rpath.dylib"
        stray_libs = {
            realpath("libs/libextfunc2_rpath.dylib"): {dep_mod: dep_path},
        }

        assert (
            delocate_wheel(
                NAMESPACE_WHEEL, "out-1.0-cp39-cp39-macosx_10_9_x86_64.whl"
            )
            == stray_libs
        )


def test_source_date_epoch() -> None:
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "package")
        for date_time, sde in (
            ((1980, 1, 1, 0, 0, 0), 42),
            ((1980, 1, 1, 0, 0, 0), 315532800),
            ((1980, 1, 1, 0, 0, 2), 315532802),
            ((2020, 2, 2, 0, 0, 0), 1580601600),
        ):
            with _scope_env(SOURCE_DATE_EPOCH=str(sde)):
                dir2zip("package", "package.zip")
            with zipfile.ZipFile("package.zip", "r") as zip:
                for name in zip.namelist():
                    member = zip.getinfo(name)
                    assert_equal(member.date_time, date_time)

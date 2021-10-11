""" Direct tests of fixes to wheels """

import os
import shutil
import stat
import subprocess
import sys
from glob import glob
from os.path import abspath, basename, exists, isdir
from os.path import join as pjoin
from os.path import realpath
from subprocess import check_call
from typing import NamedTuple

import pytest

from ..delocating import (
    DLC_PREFIX,
    DelocationError,
    delocate_wheel,
    patch_wheel,
)
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
from .pytest_tools import assert_equal, assert_false, assert_raises, assert_true
from .test_install_names import DATA_PATH, EXT_LIBS
from .test_tools import ARCH_BOTH, ARCH_M1


def _collect_wheel(globber):
    glob_path = pjoin(DATA_PATH, globber)
    wheels = glob(glob_path)
    if len(wheels) == 0:
        raise ValueError("No wheels for glob {}".format(glob_path))
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


def _fixed_wheel(out_path):
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


def _rename_module(in_wheel, mod_fname, out_wheel):
    # Rename module with library dependency in wheel
    with InWheel(in_wheel, out_wheel):
        mod_dir = pjoin("fakepkg1", "subpkg")
        os.rename(pjoin(mod_dir, "module2.abi3.so"), pjoin(mod_dir, mod_fname))
    return out_wheel


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
        assert delocate_wheel(fixed_wheel, "fixed_wheel.ext") == {
            _rp(stray_lib): {dep_mod: stray_lib}
        }
        zip2dir("fixed_wheel.ext", "plat_pkg1")
        assert exists(pjoin("plat_pkg1", "fakepkg1"))
        dylibs = pjoin("plat_pkg1", "fakepkg1", ".dylibs")
        assert exists(dylibs)
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        # Test another lib output directory
        assert delocate_wheel(
            fixed_wheel, "fixed_wheel2.ext", "dylibs_dir"
        ) == {_rp(stray_lib): {dep_mod: stray_lib}}
        zip2dir("fixed_wheel2.ext", "plat_pkg2")
        assert exists(pjoin("plat_pkg2", "fakepkg1"))
        dylibs = pjoin("plat_pkg2", "fakepkg1", "dylibs_dir")
        assert exists(dylibs)
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        # Test check for existing output directory
        with pytest.raises(DelocationError):
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


def test_fix_plat_dylibs():
    # Check default and non-default searches for dylibs
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, "module.other", "test.whl")
        # With dylibs-only - only analyze files with exts '.dylib', '.so'
        assert_equal(
            delocate_wheel("test.whl", lib_filt_func="dylibs-only"), {}
        )
        # With func that doesn't find the module

        def func(fn):
            return fn.endswith(".so")

        assert_equal(delocate_wheel("test.whl", lib_filt_func=func), {})
        # Default - looks in every file
        dep_mod = pjoin("fakepkg1", "subpkg", "module.other")
        assert_equal(
            delocate_wheel("test.whl"),
            {realpath(stray_lib): {dep_mod: stray_lib}},
        )


def _thin_lib(stray_lib, arch):
    check_call(["lipo", "-thin", arch, stray_lib, "-output", stray_lib])


def _thin_mod(wheel, arch):
    with InWheel(wheel, wheel):
        mod_fname = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
        check_call(["lipo", "-thin", arch, mod_fname, "-output", mod_fname])


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

        for arch in ("x86_64", "arm64"):
            # OK unless we check
            _fix_break(arch)
            assert_equal(
                delocate_wheel(fixed_wheel, require_archs=None),
                {realpath(stray_lib): {dep_mod: stray_lib}},
            )
            # Now we check, and error raised
            _fix_break(arch)
            assert_raises(
                DelocationError, delocate_wheel, fixed_wheel, require_archs=()
            )
            # We can fix again by thinning the module too
            _fix_break_fix(arch)
            assert_equal(
                delocate_wheel(fixed_wheel, require_archs=()),
                {realpath(stray_lib): {dep_mod: stray_lib}},
            )
            # But if we require the arch we don't have, it breaks
            for req_arch in (
                "universal2",
                ARCH_BOTH,
                ARCH_BOTH.difference([arch]),
            ):
                _fix_break_fix(arch)
                assert_raises(
                    DelocationError,
                    delocate_wheel,
                    fixed_wheel,
                    require_archs=req_arch,
                )
        # Can be verbose (we won't check output though)
        _fix_break("x86_64")
        assert_raises(
            DelocationError,
            delocate_wheel,
            fixed_wheel,
            require_archs=(),
            check_verbose=True,
        )


def test_patch_wheel() -> None:
    # Check patching of wheel
    with InTemporaryDirectory():
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        patch_wheel(PURE_WHEEL, WHEEL_PATCH, out_fname)
        zip2dir(out_fname, "wheel1")
        with open(pjoin("wheel1", "fakepkg2", "__init__.py"), "rt") as fobj:
            assert fobj.read() == 'print("Am in init")\n'
        # Check that wheel unpack works
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", out_fname], check=True
        )
        # Copy the original, check it doesn't have patch
        shutil.copyfile(PURE_WHEEL, "copied.whl")
        zip2dir("copied.whl", "wheel2")
        with open(pjoin("wheel2", "fakepkg2", "__init__.py"), "rt") as fobj:
            assert fobj.read() == ""
        # Overwrite input wheel (the default)
        patch_wheel("copied.whl", WHEEL_PATCH)
        # Patched
        zip2dir("copied.whl", "wheel3")
        with open(pjoin("wheel3", "fakepkg2", "__init__.py"), "rt") as fobj:
            assert fobj.read() == 'print("Am in init")\n'
        # Check bad patch raises error
        with pytest.raises(RuntimeError):
            patch_wheel(PURE_WHEEL, WHEEL_PATCH_BAD, "out.whl")


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

        assert delocate_wheel(RPATH_WHEEL, "tmp.whl") == stray_libs

        with InWheel("tmp.whl"):
            check_call(
                [
                    "codesign",
                    "--verify",
                    "fakepkg/.dylibs/libextfunc_rpath.dylib",
                ]
            )

        # Now test filters with recursive dependencies.
        def ignore_libextfunc(path: str) -> bool:
            """Ignore libextfunc which will also ignore its dependency and
            include no files.
            """
            return "libextfunc_rpath.dylib" not in path

        assert (
            delocate_wheel(
                RPATH_WHEEL, "tmp.whl", lib_filt_func=ignore_libextfunc
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
                RPATH_WHEEL, "tmp.whl", lib_filt_func=ignore_libextfunc2
            )
            == stray_libs_only_direct
        )


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

        assert delocate_wheel(TOPLEVEL_WHEEL, "out.whl") == stray_libs
        with InWheel("out.whl") as wheel_path:
            assert "fakepkg_toplevel.dylibs" in os.listdir(wheel_path)


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

        assert delocate_wheel(NAMESPACE_WHEEL, "out.whl") == stray_libs

""" Tests for libsana module

Utilities for analyzing library dependencies in trees and wheels
"""

import os
import shutil
import subprocess
from os.path import dirname
from os.path import join as pjoin
from os.path import realpath, relpath, split
from typing import Dict, Iterable, Text

import pytest

from ..delocating import DelocationError, filter_system_libs
from ..libsana import (
    DependencyNotFound,
    get_dependencies,
    get_prefix_stripper,
    get_rp_stripper,
    resolve_dynamic_paths,
    resolve_rpath,
    stripped_lib_dict,
    tree_libs,
    tree_libs_from_directory,
    walk_directory,
    walk_library,
    wheel_libs,
)
from ..tmpdirs import InTemporaryDirectory
from ..tools import set_install_name
from .env_tools import TempDirWithoutEnvVars
from .pytest_tools import assert_equal
from .test_install_names import (
    DATA_PATH,
    EXT_LIBS,
    LIBA,
    LIBB,
    LIBC,
    LIBSYSTEMB,
    TEST_LIB,
    _copy_libs,
)
from .test_wheelies import PLAT_WHEEL, PURE_WHEEL, RPATH_WHEEL, PlatWheel


def get_ext_dict(local_libs):
    # type: (Iterable[Text]) -> Dict[Text, Dict[Text, Text]]
    ext_deps = {}
    for ext_lib in EXT_LIBS:
        lib_deps = {}
        for local_lib in local_libs:
            lib_deps[realpath(local_lib)] = ext_lib
        ext_deps[realpath(ext_lib)] = lib_deps
    return ext_deps


@pytest.mark.filterwarnings("ignore:tree_libs:DeprecationWarning")
def test_tree_libs():
    # type: () -> None
    # Test ability to walk through tree, finding dynamic library refs
    # Copy specific files to avoid working tree cruft
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        rp_local_libs = [realpath(L) for L in local_libs]
        liba, libb, libc, test_lib = local_libs
        rp_liba, rp_libb, rp_libc, rp_test_lib = rp_local_libs
        exp_dict = get_ext_dict(local_libs)
        exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                rp_libb: {rp_libc: "libb.dylib"},
                rp_libc: {rp_test_lib: "libc.dylib"},
            }
        )
        # default - no filtering
        assert tree_libs(tmpdir) == exp_dict

        def filt(fname):
            # type: (Text) -> bool
            return fname.endswith(".dylib")

        exp_dict = get_ext_dict([liba, libb, libc])
        exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                rp_libb: {rp_libc: "libb.dylib"},
            }
        )
        # filtering
        assert tree_libs(tmpdir, filt) == exp_dict
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, "subtree")
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        st_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        st_exp_dict.update(
            {
                rp_liba: {
                    rp_libb: "liba.dylib",
                    rp_libc: "liba.dylib",
                    realpath(slibc): "liba.dylib",
                },
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert tree_libs(tmpdir, filt) == st_exp_dict
        # Change an install name, check this is picked up
        set_install_name(slibc, "liba.dylib", "newlib")
        inc_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        inc_exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                realpath("newlib"): {realpath(slibc): "newlib"},
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert tree_libs(tmpdir, filt) == inc_exp_dict
        # Symlink a depending canonical lib - should have no effect because of
        # the canonical names
        os.symlink(liba, pjoin(dirname(liba), "funny.dylib"))
        assert tree_libs(tmpdir, filt) == inc_exp_dict
        # Symlink a depended lib.  Now 'newlib' is a symlink to liba, and the
        # dependency of slibc on newlib appears as a dependency on liba, but
        # with install name 'newlib'
        os.symlink(liba, "newlib")
        sl_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        sl_exp_dict.update(
            {
                rp_liba: {
                    rp_libb: "liba.dylib",
                    rp_libc: "liba.dylib",
                    realpath(slibc): "newlib",
                },
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert tree_libs(tmpdir, filt) == sl_exp_dict


def test_tree_libs_from_directory() -> None:
    # Test ability to walk through tree, finding dynamic library refs
    # Copy specific files to avoid working tree cruft
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        rp_local_libs = [realpath(L) for L in local_libs]
        liba, libb, libc, test_lib = local_libs
        rp_liba, rp_libb, rp_libc, rp_test_lib = rp_local_libs
        exp_dict = get_ext_dict(local_libs)
        exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                rp_libb: {rp_libc: "libb.dylib"},
                rp_libc: {rp_test_lib: "libc.dylib"},
            }
        )
        # default - no filtering
        assert tree_libs_from_directory(tmpdir) == exp_dict

        def filt(fname: str) -> bool:
            return filter_system_libs(fname) and fname.endswith(".dylib")

        exp_dict = get_ext_dict([liba, libb, libc])
        exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                rp_libb: {rp_libc: "libb.dylib"},
            }
        )
        # filtering
        assert tree_libs_from_directory(tmpdir, lib_filt_func=filt) == exp_dict
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, "subtree")
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        st_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        st_exp_dict.update(
            {
                rp_liba: {
                    rp_libb: "liba.dylib",
                    rp_libc: "liba.dylib",
                    realpath(slibc): "liba.dylib",
                },
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert (
            tree_libs_from_directory(tmpdir, lib_filt_func=filt) == st_exp_dict
        )
        # Change an install name, check this is ignored
        set_install_name(slibc, "liba.dylib", "newlib")
        inc_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        inc_exp_dict.update(
            {
                rp_liba: {rp_libb: "liba.dylib", rp_libc: "liba.dylib"},
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert (
            tree_libs_from_directory(
                tmpdir, lib_filt_func=filt, ignore_missing=True
            )
            == inc_exp_dict
        )
        # Symlink a depending canonical lib - should have no effect because of
        # the canonical names
        os.symlink(liba, pjoin(dirname(liba), "funny.dylib"))
        assert (
            tree_libs_from_directory(
                tmpdir, lib_filt_func=filt, ignore_missing=True
            )
            == inc_exp_dict
        )
        # Symlink a depended lib.  Now 'newlib' is a symlink to liba, and the
        # dependency of slibc on newlib appears as a dependency on liba, but
        # with install name 'newlib'
        os.symlink(liba, "newlib")
        sl_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        sl_exp_dict.update(
            {
                rp_liba: {
                    rp_libb: "liba.dylib",
                    rp_libc: "liba.dylib",
                    realpath(slibc): "newlib",
                },
                rp_libb: {
                    rp_libc: "libb.dylib",
                    realpath(slibc): "libb.dylib",
                },
            }
        )
        assert (
            tree_libs_from_directory(
                tmpdir, lib_filt_func=filt, ignore_missing=True
            )
            == sl_exp_dict
        )


def test_tree_libs_from_directory_with_links() -> None:
    # Test ability to walk through tree, where the same library may have
    # soft links under different subdirectories. See also GH#133, where
    # we have:
    #
    #   liba.dylib
    #   links/liba.dylib, a soft link to liba.dylib
    #
    # and
    #
    #   libb.dylib, depends on liba.dylib via `@rpath/liba.dylib`
    #   links/libb.dylib, depends on links/liba.dylib and been found via
    #                     `DYLD_LIBRARY_PATH`
    #
    # in the final target we should keep the `liba.dylib` for only once, rather
    # than throwing a DelocationError.
    to_copy = [
        LIBA,
        LIBB,
    ]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        rp_local_libs = [realpath(L) for L in local_libs]
        (
            liba,
            libb,
        ) = local_libs
        (
            rp_liba,
            rp_libb,
        ) = rp_local_libs

        # copy files
        os.makedirs(pjoin(tmpdir, "links"))
        liba_link = pjoin(tmpdir, "links", "liba.dylib")
        libb_use_link = pjoin(tmpdir, "links", "libb.dylib")
        rp_libb_use_link = realpath(libb_use_link)
        os.symlink(liba, liba_link)
        shutil.copy2(libb, libb_use_link)

        # hack links/libb.dylib to depend on the softlink of liba.dylib
        subprocess.check_call(
            [
                "install_name_tool",
                "-change",
                "liba.dylib",
                liba_link,
                libb_use_link,
            ]
        )
        # hack libb.dylib to resolve from rpath, bypass searching from env
        subprocess.check_call(
            [
                "install_name_tool",
                "-change",
                "liba.dylib",
                "@rpath/liba.dylib",
                libb,
            ]
        )
        subprocess.check_call(
            [
                "install_name_tool",
                "-add_rpath",
                os.path.dirname(liba),
                libb,
            ]
        )

        exp_dict = get_ext_dict(local_libs + [liba_link, libb_use_link])
        exp_dict.update(
            {
                rp_liba: {
                    rp_libb: "@rpath/liba.dylib",
                    rp_libb_use_link: liba_link,
                },
            }
        )

        # Put dir of soft link for `liba.dylib` into `DYLD_LIBRARY_PATH`
        with TempDirWithoutEnvVars("DYLD_LIBRARY_PATH"):
            # the result should be correct normally
            assert tree_libs_from_directory(tmpdir) == exp_dict

            # the result should be correct even if there are soft links in
            # `$DYLD_LIBRARY_PATH`
            os.environ["DYLD_LIBRARY_PATH"] = os.path.dirname(liba_link)
            assert tree_libs_from_directory(tmpdir) == exp_dict


def test_get_prefix_stripper():
    # type: () -> None
    # Test function factory to strip prefixes
    f = get_prefix_stripper("")
    assert_equal(f("a string"), "a string")
    f = get_prefix_stripper("a ")
    assert_equal(f("a string"), "string")
    assert_equal(f("b string"), "b string")
    assert_equal(f("b a string"), "b a string")


def test_get_rp_stripper():
    # type: () -> None
    # realpath prefix stripper
    # Just does realpath and adds path sep
    cwd = realpath(os.getcwd())
    f = get_rp_stripper("")  # pwd
    test_path = pjoin("test", "path")
    assert_equal(f(test_path), test_path)
    rp_test_path = pjoin(cwd, test_path)
    assert_equal(f(rp_test_path), test_path)
    f = get_rp_stripper(pjoin(cwd, "test"))
    assert_equal(f(rp_test_path), "path")


def get_ext_dict_stripped(local_libs, start_path):
    # type: (Iterable[Text], Text) -> Dict[Text, Dict[Text, Text]]
    ext_dict = {}
    for ext_lib in EXT_LIBS:
        lib_deps = {}
        for local_lib in local_libs:
            dep_path = relpath(local_lib, start_path)
            if dep_path.startswith("./"):
                dep_path = dep_path[2:]
            lib_deps[dep_path] = ext_lib
        ext_dict[realpath(ext_lib)] = lib_deps
    return ext_dict


def test_stripped_lib_dict():
    # type: () -> None
    # Test routine to return lib_dict with relative paths
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        exp_dict = get_ext_dict_stripped(local_libs, tmpdir)
        exp_dict.update(
            {
                "liba.dylib": {
                    "libb.dylib": "liba.dylib",
                    "libc.dylib": "liba.dylib",
                },
                "libb.dylib": {"libc.dylib": "libb.dylib"},
                "libc.dylib": {"test-lib": "libc.dylib"},
            }
        )
        my_path = realpath(tmpdir) + os.path.sep
        assert (
            stripped_lib_dict(tree_libs_from_directory(tmpdir), my_path)
            == exp_dict
        )
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, "subtree")
        liba, libb, libc, test_lib = local_libs
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        exp_dict = get_ext_dict_stripped(
            local_libs + [slibc, stest_lib], tmpdir
        )
        exp_dict.update(
            {
                "liba.dylib": {
                    "libb.dylib": "liba.dylib",
                    "libc.dylib": "liba.dylib",
                    "subtree/libc.dylib": "liba.dylib",
                },
                "libb.dylib": {
                    "libc.dylib": "libb.dylib",
                    "subtree/libc.dylib": "libb.dylib",
                },
                "libc.dylib": {
                    "test-lib": "libc.dylib",
                    "subtree/test-lib": "libc.dylib",
                },
            }
        )
        assert (
            stripped_lib_dict(tree_libs_from_directory(tmpdir), my_path)
            == exp_dict
        )


def test_wheel_libs(plat_wheel: PlatWheel) -> None:
    # Test routine to list dependencies from wheels
    assert wheel_libs(PURE_WHEEL) == {}
    mod2 = pjoin("fakepkg1", "subpkg", "module2.abi3.so")

    assert wheel_libs(plat_wheel.whl) == {
        plat_wheel.stray_lib: {mod2: plat_wheel.stray_lib},
        realpath(LIBSYSTEMB): {
            mod2: LIBSYSTEMB,
            plat_wheel.stray_lib: LIBSYSTEMB,
        },
    }

    def filt(fname: str) -> bool:
        return not fname.endswith(mod2)

    assert wheel_libs(PLAT_WHEEL, filt) == {}


def test_wheel_libs_ignore_missing() -> None:
    # Test wheel_libs ignore_missing parameter.
    with InTemporaryDirectory() as tmpdir:
        shutil.copy(RPATH_WHEEL, pjoin(tmpdir, "rpath.whl"))
        with pytest.raises(DelocationError):
            wheel_libs("rpath.whl")
        wheel_libs("rpath.whl", ignore_missing=True)


def test_resolve_dynamic_paths():
    # type: () -> None
    # A minimal test of the resolve_rpath function
    path, lib = split(LIBA)
    lib_rpath = pjoin("@rpath", lib)
    # Should skip '/nonexist' path
    assert resolve_dynamic_paths(
        lib_rpath, ["/nonexist", path], path
    ) == realpath(LIBA)
    # Should raise DependencyNotFound if the dependency can not be resolved.
    with pytest.raises(DependencyNotFound):
        resolve_dynamic_paths(lib_rpath, [], path)


def test_resolve_rpath():
    # type: () -> None
    # A minimal test of the resolve_rpath function
    path, lib = split(LIBA)
    lib_rpath = pjoin("@rpath", lib)
    # Should skip '/nonexist' path
    assert_equal(resolve_rpath(lib_rpath, ["/nonexist", path]), realpath(LIBA))
    # Should return the given parameter as is since it can't be found
    assert_equal(resolve_rpath(lib_rpath, []), lib_rpath)


def test_get_dependencies(tmpdir):
    # type: (object) -> None
    tmpdir = str(tmpdir)
    with pytest.raises(DependencyNotFound):
        list(get_dependencies("nonexistent.lib"))
    ext_libs = {(lib, lib) for lib in EXT_LIBS}
    assert set(get_dependencies(LIBA)) == ext_libs

    os.symlink(
        pjoin(DATA_PATH, "libextfunc_rpath.dylib"),
        pjoin(tmpdir, "libextfunc_rpath.dylib"),
    )
    assert set(
        get_dependencies(
            pjoin(tmpdir, "libextfunc_rpath.dylib"),
            filt_func=filter_system_libs,
        )
    ) == {
        (None, "@rpath/libextfunc2_rpath.dylib"),
        (LIBSYSTEMB, LIBSYSTEMB),
    }

    assert set(
        get_dependencies(
            pjoin(tmpdir, "libextfunc_rpath.dylib"),
            executable_path=DATA_PATH,
            filt_func=filter_system_libs,
        )
    ) == {
        (
            pjoin(DATA_PATH, "libextfunc2_rpath.dylib"),
            "@rpath/libextfunc2_rpath.dylib",
        ),
        (LIBSYSTEMB, LIBSYSTEMB),
    }


def test_walk_library():
    # type: () -> None
    with pytest.raises(DependencyNotFound):
        list(walk_library("nonexistent.lib"))
    assert set(walk_library(LIBA, filt_func=filter_system_libs)) == {
        LIBA,
    }
    assert set(
        walk_library(
            pjoin(DATA_PATH, "libextfunc_rpath.dylib"),
            filt_func=filter_system_libs,
        )
    ) == {
        pjoin(DATA_PATH, "libextfunc_rpath.dylib"),
        pjoin(DATA_PATH, "libextfunc2_rpath.dylib"),
    }


def test_walk_directory(tmpdir):
    # type: (object) -> None
    tmpdir = str(tmpdir)
    assert set(walk_directory(tmpdir)) == set()

    shutil.copy(pjoin(DATA_PATH, "libextfunc_rpath.dylib"), tmpdir)
    assert set(walk_directory(tmpdir, filt_func=filter_system_libs)) == {
        pjoin(tmpdir, "libextfunc_rpath.dylib"),
    }

    assert set(
        walk_directory(
            tmpdir, executable_path=DATA_PATH, filt_func=filter_system_libs
        )
    ) == {
        pjoin(tmpdir, "libextfunc_rpath.dylib"),
        pjoin(DATA_PATH, "libextfunc2_rpath.dylib"),
    }

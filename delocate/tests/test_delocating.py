""" Tests for relocating libraries """

from __future__ import division, print_function

import os
import shutil
import subprocess
from collections import namedtuple
from os.path import basename, dirname
from os.path import join as pjoin
from os.path import realpath, relpath, splitext
from typing import Any, Callable, Dict, Iterable, List, Set, Text, Tuple

import pytest

from ..delocating import (
    DelocationError,
    bads_report,
    check_archs,
    copy_recurse,
    delocate_path,
    delocate_tree_libs,
    filter_system_libs,
)
from ..libsana import (
    search_environment_for_lib,
    tree_libs,
    tree_libs_from_directory,
)
from ..tmpdirs import InTemporaryDirectory
from ..tools import get_install_names, set_install_name
from .env_tools import TempDirWithoutEnvVars
from .pytest_tools import assert_equal, assert_raises
from .test_install_names import EXT_LIBS, LIBA, LIBB, LIBC, TEST_LIB, _copy_libs
from .test_tools import (
    ARCH_32,
    ARCH_64,
    ARCH_BOTH,
    ARCH_M1,
    LIB64,
    LIB64A,
    LIBBOTH,
    LIBM1,
)

LibtreeLibs = namedtuple(
    "LibtreeLibs", ("liba", "libb", "libc", "test_lib", "slibc", "stest_lib")
)


def _make_libtree(out_path: str) -> LibtreeLibs:
    liba, libb, libc, test_lib = _copy_libs(
        [LIBA, LIBB, LIBC, TEST_LIB], out_path
    )
    sub_path = pjoin(out_path, "subsub")
    slibc, stest_lib = _copy_libs([libc, test_lib], sub_path)
    # Set execute permissions
    for exe in (test_lib, stest_lib):
        os.chmod(exe, 0o744)
    # Check test-lib doesn't work because of relative library paths
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([test_lib], check=True)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([stest_lib], check=True)
    # Fixup the relative path library names by setting absolute paths
    for fname, using, path in (
        (libb, "liba.dylib", out_path),
        (libc, "liba.dylib", out_path),
        (libc, "libb.dylib", out_path),
        (test_lib, "libc.dylib", out_path),
        (slibc, "liba.dylib", out_path),
        (slibc, "libb.dylib", out_path),
        (stest_lib, "libc.dylib", sub_path),
    ):
        set_install_name(fname, using, pjoin(path, using))
    # Check scripts now execute correctly
    subprocess.run([test_lib], check=True)
    subprocess.run([stest_lib], check=True)
    return LibtreeLibs(liba, libb, libc, test_lib, slibc, stest_lib)


def without_system_libs(obj):
    # Until Big Sur, we could copy system libraries.  Now:
    # https://developer.apple.com/documentation/macos-release-notes/macos-big-sur-11_0_1-release-notes
    # - nearly all the system libraries are in a dynamic linker cache and
    # do not exist on the filesystem.  We're obliged to use
    # `filter_system_libs` to avoid trying to copy these files.
    out = [e for e in obj if filter_system_libs(e)]
    if isinstance(obj, dict):
        out = {k: obj[k] for k in out}
    return out


@pytest.mark.filterwarnings("ignore:tree_libs:DeprecationWarning")
@pytest.mark.parametrize(
    "tree_libs_func", [tree_libs, tree_libs_from_directory]
)
def test_delocate_tree_libs(
    tree_libs_func: Callable[[str], Dict[Text, Dict[Text, Text]]]
) -> None:
    # Test routine to copy library dependencies into a local directory
    with InTemporaryDirectory() as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, "subtree")
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        copy_dir = "dynlibs"
        os.makedirs(copy_dir)
        # First check that missing out-of-system tree library causes error.
        sys_lib = EXT_LIBS[0]
        lib_dict = without_system_libs(tree_libs_func(subtree))
        lib_dict.update({"/unlikely/libname.dylib": {}})
        with pytest.raises(DelocationError):
            delocate_tree_libs(lib_dict, copy_dir, subtree)

        lib_dict = without_system_libs(tree_libs_func(subtree))
        copied = delocate_tree_libs(lib_dict, copy_dir, subtree)
        # There are no out-of-tree libraries, nothing gets copied
        assert len(copied) == 0
        # Make an out-of-tree library to test against.
        os.makedirs("out_of_tree")
        fake_lib = realpath(pjoin("out_of_tree", "libfake.dylib"))
        shutil.copyfile(liba, fake_lib)
        set_install_name(liba, sys_lib, fake_lib)
        lib_dict = without_system_libs(tree_libs_func(subtree))
        copied = delocate_tree_libs(lib_dict, copy_dir, subtree)
        # Out-of-tree library copied.
        assert copied == {fake_lib: {realpath(liba): fake_lib}}
        assert os.listdir(copy_dir) == [basename(fake_lib)]
        # Library using the copied library now has an
        # install name starting with @loader_path, then
        # pointing to the copied library directory
        pathto_copies = relpath(realpath(copy_dir), dirname(realpath(liba)))
        lib_inames = without_system_libs(get_install_names(liba))
        new_link = f"@loader_path/{pathto_copies}/{basename(fake_lib)}"
        assert [new_link] <= lib_inames
        # Libraries now have a relative loader_path to their corresponding
        # in-tree libraries
        for requiring, using, rel_path in (
            (libb, "liba.dylib", ""),
            (libc, "liba.dylib", ""),
            (libc, "libb.dylib", ""),
            (test_lib, "libc.dylib", ""),
            (slibc, "liba.dylib", "../"),
            (slibc, "libb.dylib", "../"),
            (stest_lib, "libc.dylib", ""),
        ):
            loader_path = "@loader_path/" + rel_path + using
            not_sys_req = without_system_libs(get_install_names(requiring))
            assert loader_path in not_sys_req
        # Another copy to delocate, now without faked out-of-tree dependency.
        subtree = pjoin(tmpdir, "subtree1")
        out_libs = _make_libtree(subtree)
        lib_dict = without_system_libs(tree_libs_func(subtree))
        copied = delocate_tree_libs(lib_dict, copy_dir, subtree)
        # Now no out-of-tree libraries, nothing copied.
        assert copied == {}
        # Check test libs still work
        subprocess.run([out_libs.test_lib], check=True)
        subprocess.run([out_libs.stest_lib], check=True)
        # Check case where all local libraries are out of tree
        subtree2 = pjoin(tmpdir, "subtree2")
        liba, libb, libc, test_lib, slibc, stest_lib = _make_libtree(subtree2)
        copy_dir2 = "dynlibs2"
        os.makedirs(copy_dir2)
        # Trying to delocate where all local libraries appear to be
        # out-of-tree will raise an error because of duplicate library names
        # (libc and slibc both named <something>/libc.dylib)
        lib_dict2 = without_system_libs(tree_libs_func(subtree2))
        with pytest.raises(DelocationError):
            delocate_tree_libs(lib_dict2, copy_dir2, "/fictional")
        # Rename a library to make this work
        new_slibc = pjoin(dirname(slibc), "libc2.dylib")
        os.rename(slibc, new_slibc)
        # Tell test-lib about this
        set_install_name(stest_lib, slibc, new_slibc)
        slibc = new_slibc
        # Confirm new test-lib still works
        subprocess.run([test_lib], check=True)
        subprocess.run([stest_lib], check=True)
        # Delocation now works
        lib_dict2 = without_system_libs(tree_libs_func(subtree2))
        copied2 = delocate_tree_libs(lib_dict2, copy_dir2, "/fictional")
        local_libs = [liba, libb, libc, slibc, test_lib, stest_lib]
        rp_liba, rp_libb, rp_libc, rp_slibc, rp_test_lib, rp_stest_lib = [
            realpath(L) for L in local_libs
        ]
        exp_dict = {
            rp_libc: {rp_test_lib: libc},
            rp_slibc: {rp_stest_lib: slibc},
            rp_libb: {rp_slibc: libb, rp_libc: libb},
            rp_liba: {rp_slibc: liba, rp_libc: liba, rp_libb: liba},
        }
        assert copied2 == exp_dict
        ext_local_libs = {liba, libb, libc, slibc}
        assert set(os.listdir(copy_dir2)) == {
            basename(lib) for lib in ext_local_libs
        }
        # Libraries using the copied libraries now have an install name starting
        # with @loader_path, then pointing to the copied library directory
        for lib in (liba, libb, libc, test_lib, slibc, stest_lib):
            pathto_copies = relpath(realpath(copy_dir2), dirname(realpath(lib)))
            lib_inames = get_install_names(lib)
            new_links = [
                f"@loader_path/{pathto_copies}/{basename(elib)}"
                for elib in copied
            ]
            assert set(new_links) <= set(lib_inames)


def _copy_fixpath(files: Iterable[str], directory: str) -> List[str]:
    new_fnames = []
    for fname in files:
        shutil.copy2(fname, directory)
        new_fname = pjoin(directory, basename(fname))
        for name in get_install_names(fname):
            if name.startswith("lib"):
                set_install_name(new_fname, name, pjoin(directory, name))
        new_fnames.append(new_fname)
    return new_fnames


def _copy_to(fname: str, directory: str, new_base: str) -> str:
    new_name = pjoin(directory, new_base)
    shutil.copy2(fname, new_name)
    return new_name


@pytest.mark.filterwarnings("ignore:tree_libs:DeprecationWarning")
@pytest.mark.filterwarnings("ignore:copy_recurse:DeprecationWarning")
def test_copy_recurse() -> None:
    # Function to find / copy needed libraries recursively
    with InTemporaryDirectory():
        # Get some fixed up libraries to play with
        os.makedirs("libcopy")
        test_lib, liba, libb, libc = _copy_fixpath(
            [TEST_LIB, LIBA, LIBB, LIBC], "libcopy"
        )
        # Set execute permissions
        os.chmod(test_lib, 0o744)
        # Check system finds libraries
        subprocess.run(["./libcopy/test-lib"], check=True)
        # One library, depends only on system libs, system libs filtered

        def filt_func(libname: str) -> bool:
            return not libname.startswith("/usr/lib")

        os.makedirs("subtree")
        _copy_fixpath([LIBA], "subtree")
        # Nothing copied therefore
        assert copy_recurse("subtree", copy_filt_func=filt_func) == {}
        assert set(os.listdir("subtree")) == {"liba.dylib"}
        # shortcut
        _rp = realpath
        # An object that depends on a library that depends on two libraries
        # test_lib depends on libc, libc depends on liba and libb. libc gets
        # copied first, then liba, libb

        def _st(fname: str) -> str:
            return _rp(pjoin("subtree2", basename(fname)))

        os.makedirs("subtree2")
        shutil.copy2(test_lib, "subtree2")
        assert copy_recurse("subtree2", filt_func) == {
            _rp(libc): {_st(test_lib): libc},
            _rp(libb): {_rp(libc): libb},
            _rp(liba): {_rp(libb): liba, _rp(libc): liba},
        }
        assert set(os.listdir("subtree2")) == {
            "liba.dylib",
            "libb.dylib",
            "libc.dylib",
            "test-lib",
        }
        # A circular set of libraries
        os.makedirs("libcopy2")
        libw = _copy_to(LIBA, "libcopy2", "libw.dylib")
        libx = _copy_to(LIBA, "libcopy2", "libx.dylib")
        liby = _copy_to(LIBA, "libcopy2", "liby.dylib")
        libz = _copy_to(LIBA, "libcopy2", "libz.dylib")
        # targets and dependencies.  A copy of libw starts in the directory,
        # first pass should install libx and liby (dependencies of libw),
        # second pass should install libz, libw (dependencies of liby, libx
        # respectively)
        t_dep1_dep2 = (
            (libw, libx, liby),  # libw depends on libx, liby
            (libx, libw, liby),  # libx depends on libw, liby
            (liby, libw, libz),  # liby depends on libw, libz
            (libz, libw, libx),
        )  # libz depends on libw, libx
        for tlib, dep1, dep2 in t_dep1_dep2:
            set_install_name(tlib, EXT_LIBS[0], dep1)
            set_install_name(tlib, EXT_LIBS[1], dep2)
        os.makedirs("subtree3")
        seed_path = pjoin("subtree3", "seed")
        shutil.copy2(libw, seed_path)
        assert copy_recurse("subtree3") == {  # not filtered
            # First pass, libx, liby get copied
            _rp(libx): {
                _rp(seed_path): libx,
                _rp(libw): libx,
                _rp(libz): libx,
            },
            _rp(liby): {
                _rp(seed_path): liby,
                _rp(libw): liby,
                _rp(libx): liby,
            },
            _rp(libw): {_rp(libx): libw, _rp(liby): libw, _rp(libz): libw},
            _rp(libz): {_rp(liby): libz},
        }
        assert set(os.listdir("subtree3")) == {
            "seed",
            "libw.dylib",
            "libx.dylib",
            "liby.dylib",
            "libz.dylib",
        }
        for tlib, dep1, dep2 in t_dep1_dep2:
            out_lib = pjoin("subtree3", basename(tlib))
            assert set(get_install_names(out_lib)) == {
                "@loader_path/" + basename(dep1),
                "@loader_path/" + basename(dep2),
            }
        # Check case of not-empty copied_libs
        os.makedirs("subtree4")
        shutil.copy2(libw, "subtree4")
        copied_libs = {
            _rp(libw): {_rp(libx): libw, _rp(liby): libw, _rp(libz): libw}
        }
        copied_copied = copied_libs.copy()
        assert copy_recurse("subtree4", None, copied_libs) == {
            _rp(libw): {_rp(libx): libw, _rp(liby): libw, _rp(libz): libw},
            _rp(libx): {_rp(libw): libx, _rp(libz): libx},
            _rp(liby): {_rp(libw): liby, _rp(libx): liby},
            _rp(libz): {_rp(liby): libz},
        }
        # Not modified in-place
        assert copied_libs == copied_copied


@pytest.mark.filterwarnings("ignore:tree_libs:DeprecationWarning")
@pytest.mark.filterwarnings("ignore:copy_recurse:DeprecationWarning")
def test_copy_recurse_overwrite():
    # type: () -> None
    # Check that copy_recurse won't overwrite pre-existing libs
    with InTemporaryDirectory():
        # Get some fixed up libraries to play with
        os.makedirs("libcopy")
        test_lib, liba, libb, libc = _copy_fixpath(
            [TEST_LIB, LIBA, LIBB, LIBC], "libcopy"
        )
        # Filter system libs

        def filt_func(libname):
            # type: (Text) -> bool
            return not libname.startswith("/usr/lib")

        os.makedirs("subtree")
        # libb depends on liba
        shutil.copy2(libb, "subtree")
        # If liba is already present, barf
        shutil.copy2(liba, "subtree")
        assert_raises(DelocationError, copy_recurse, "subtree", filt_func)
        # Works if liba not present
        os.unlink(pjoin("subtree", "liba.dylib"))
        copy_recurse("subtree", filt_func)


def test_delocate_path() -> None:
    # Test high-level path delocator script
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(realpath("subtree"))
        # Check it fixes up correctly
        assert delocate_path("subtree", "deplibs") == {}
        assert len(os.listdir("deplibs")) == 0
        subprocess.run([test_lib], check=True)
        subprocess.run([stest_lib], check=True)
        # Make a fake external library to link to
        os.makedirs("fakelibs")
        fake_lib = realpath(_copy_to(LIBA, "fakelibs", "libfake.dylib"))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree2")
        )
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # shortcut
        _rp = realpath
        # Check fake libary gets copied and delocated
        slc_rel = pjoin("subtree2", "subsub", "libc.dylib")
        assert delocate_path("subtree2", "deplibs2") == {
            _rp(fake_lib): {_rp(slc_rel): fake_lib}
        }
        assert os.listdir("deplibs2") == ["libfake.dylib"]
        assert "@loader_path/../../deplibs2/libfake.dylib" in get_install_names(
            slibc
        )
        # Unless we set the filter otherwise
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree3")
        )
        set_install_name(slibc, EXT_LIBS[0], fake_lib)

        def filt(libname: str) -> bool:
            return not (libname.startswith("/usr") or "libfake" in libname)

        assert delocate_path("subtree3", "deplibs3", None, filt) == {}
        assert len(os.listdir("deplibs3")) == 0
        # Test tree names filtering works
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree4")
        )
        set_install_name(slibc, EXT_LIBS[0], fake_lib)

        def lib_filt(filename: str) -> bool:
            return not filename.endswith("subsub/libc.dylib")

        assert delocate_path("subtree4", "deplibs4", lib_filt) == {}
        assert len(os.listdir("deplibs4")) == 0
        # Check can use already existing directory
        os.makedirs("deplibs5")
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree5")
        )
        assert delocate_path("subtree5", "deplibs5") == {}
        assert len(os.listdir("deplibs5")) == 0
        # Check invalid string
        with pytest.raises(TypeError):
            delocate_path("subtree5", "deplibs5", lib_filt_func="invalid-str")


def _make_bare_depends():
    # type: () -> Tuple[Text, Text]
    # Copy:
    # * liba.dylib to 'libs' dir, which is a dependency of libb.dylib
    # * libb.dylib to 'subtree' dir, as 'libb' (no extension).
    #
    # This is for testing delocation when the depending file does not have a
    # dynamic library file extension.
    (libb,) = _copy_libs([LIBB], "subtree")
    (liba,) = _copy_libs([LIBA], "libs")
    bare_b, _ = splitext(libb)
    os.rename(libb, bare_b)
    # use realpath for OSX /private/var - /var
    set_install_name(bare_b, "liba.dylib", realpath(liba))
    return liba, bare_b


def test_delocate_path_dylibs():
    # type: () -> None
    # Test options for delocating everything, or just dynamic libraries
    _rp = realpath  # shortcut
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        assert_equal(
            delocate_path("subtree", "deplibs", lib_filt_func="dylibs-only"),
            {},
        )
        assert_equal(len(os.listdir("deplibs")), 0)
        # None - does inspect non-dylib files
        assert_equal(
            delocate_path("subtree", "deplibs", None),
            {_rp(pjoin("libs", "liba.dylib")): {_rp(bare_b): _rp(liba)}},
        )
        assert_equal(os.listdir("deplibs"), ["liba.dylib"])
    with InTemporaryDirectory():
        # Callable, dylibs only, does not inspect
        liba, bare_b = _make_bare_depends()

        def func(fn):
            # type: (Text) -> bool
            return fn.endswith(".dylib")

        assert_equal(delocate_path("subtree", "deplibs", func), {})

        def func(fn):
            # type: (Text) -> bool
            return fn.endswith("libb")

        assert_equal(
            delocate_path("subtree", "deplibs", None),
            {_rp(pjoin("libs", "liba.dylib")): {_rp(bare_b): _rp(liba)}},
        )


def test_check_archs():
    # type: () -> None
    # Test utility to check architectures in copied_libs dict
    # No libs always OK
    s0 = set()  # type: Set[Any]
    assert_equal(check_archs({}), s0)
    # One lib to itself OK
    lib_M1_M1 = {LIBM1: {LIBM1: "install_name"}}
    lib_64_64 = {LIB64: {LIB64: "install_name"}}
    assert_equal(check_archs(lib_M1_M1), s0)
    assert_equal(check_archs(lib_64_64), s0)
    # OK matching to another static lib of same arch
    assert_equal(check_archs({LIB64A: {LIB64: "install_name"}}), s0)
    # Or two libs
    two_libs = {
        LIB64A: {LIB64: "install_name"},
        LIBM1: {LIBM1: "install_name"},
    }
    assert_equal(check_archs(two_libs), s0)
    # Same as empty sequence required_args argument
    assert_equal(check_archs(lib_M1_M1, ()), s0)
    assert_equal(check_archs(lib_64_64, ()), s0)
    assert_equal(check_archs(two_libs, ()), s0)
    assert_equal(check_archs(two_libs, []), s0)
    assert_equal(check_archs(two_libs, set()), s0)
    # bads if we require more archs than present
    for in_libs, exp_arch, missing in (
        (lib_M1_M1, ARCH_64, ARCH_64),
        (lib_M1_M1, ARCH_BOTH, ARCH_64),
        (lib_M1_M1, "x86_64", ARCH_64),
        (lib_M1_M1, "universal2", ARCH_64),
        (lib_64_64, ARCH_M1, ARCH_M1),
        (lib_64_64, ARCH_BOTH, ARCH_M1),
        (lib_64_64, "arm64", ARCH_M1),
        (lib_64_64, "intel", ARCH_32),
        (lib_64_64, "universal2", ARCH_M1),
    ):
        ded, value = list(in_libs.items())[0]
        ding, _ = list(value.items())[0]
        arch_check = check_archs(in_libs, exp_arch)
        assert_equal(arch_check, {(ding, missing)})
    # Two libs
    assert_equal(check_archs(two_libs, ARCH_M1), {(LIB64, ARCH_M1)})
    assert_equal(check_archs(two_libs, ARCH_64), {(LIBM1, ARCH_64)})
    assert_equal(
        check_archs(two_libs, ARCH_BOTH), {(LIB64, ARCH_M1), (LIBM1, ARCH_64)}
    )
    # Libs must match architecture with second arg of None
    assert_equal(
        check_archs({LIB64: {LIBM1: "install_name"}}),
        {(LIB64, LIBM1, ARCH_M1)},
    )
    assert_equal(
        check_archs(
            {
                LIB64A: {LIB64: "install_name"},
                LIBM1: {LIBM1: "install_name"},
                LIB64: {LIBM1: "install_name"},
            }
        ),
        {(LIB64, LIBM1, ARCH_M1)},
    )
    # For single archs depending, dual archs in depended is OK
    assert check_archs({LIBBOTH: {LIB64A: "install_name"}}) == s0
    # For dual archs in depending, both must be present
    assert_equal(check_archs({LIBBOTH: {LIBBOTH: "install_name"}}), s0)
    assert_equal(
        check_archs({LIB64A: {LIBBOTH: "install_name"}}),
        {(LIB64A, LIBBOTH, ARCH_M1)},
    )
    # More than one bad
    in_dict = {
        LIB64A: {LIBBOTH: "install_name"},
        LIB64: {LIBM1: "install_name"},
    }
    exp_res = {(LIB64A, LIBBOTH, ARCH_M1), (LIB64, LIBM1, ARCH_M1)}
    assert_equal(check_archs(in_dict), exp_res)
    # Check stop_fast flag; can't predict return, but there should only be one
    stopped = check_archs(in_dict, (), True)
    assert_equal(len(stopped), 1)
    # More than one bad in dependings
    assert_equal(
        check_archs(
            {
                LIB64A: {LIBBOTH: "install_name", LIBM1: "install_name"},
                LIB64: {LIBM1: "install_name"},
            }
        ),
        {
            (LIB64A, LIBBOTH, ARCH_M1),
            (LIB64A, LIBM1, ARCH_M1),
            (LIB64, LIBM1, ARCH_M1),
        },
    )


def test_bads_report():
    # type: () -> None
    # Test bads_report of architecture errors
    # No bads, no report
    assert_equal(bads_report(set()), "")
    fmt_str_2 = "Required arch arm64 missing from {0}"
    fmt_str_3 = "{0} needs arch arm64 missing from {1}"
    # One line report
    assert_equal(
        bads_report({(LIB64, LIBM1, ARCH_M1)}), fmt_str_3.format(LIBM1, LIB64)
    )
    # One line report applying path stripper
    assert_equal(
        bads_report({(LIB64, LIBM1, ARCH_M1)}, dirname(LIB64)),
        fmt_str_3.format(basename(LIBM1), basename(LIB64)),
    )
    # Multi-line report
    report = bads_report(
        {
            (LIB64A, LIBBOTH, ARCH_M1),
            (LIB64A, LIBM1, ARCH_M1),
            (LIB64, LIBM1, ARCH_M1),
        }
    )
    expected = {
        fmt_str_3.format(LIBM1, LIB64A),
        fmt_str_3.format(LIBM1, LIB64),
        fmt_str_3.format(LIBBOTH, LIB64A),
    }
    # Set ordering undefined.
    assert_equal(set(report.splitlines()), expected)
    # Two tuples and three tuples
    report2 = bads_report(
        {(LIB64A, LIBBOTH, ARCH_M1), (LIB64, ARCH_M1), (LIBM1, ARCH_M1)}
    )
    expected2 = {
        fmt_str_3.format(LIBBOTH, LIB64A),
        fmt_str_2.format(LIB64),
        fmt_str_2.format(LIBM1),
    }
    assert_equal(set(report2.splitlines()), expected2)
    # Tuples must be length 2 or 3
    assert_raises(
        ValueError,
        bads_report,
        {(LIB64A, LIBBOTH, ARCH_M1), (LIB64,), (LIBM1, ARCH_M1)},
    )
    # Tuples must be length 2 or 3
    assert_raises(
        ValueError,
        bads_report,
        {
            (LIB64A, LIBBOTH, ARCH_M1),
            (LIB64, LIB64, ARCH_M1, ARCH_64),
            (LIBM1, ARCH_M1),
        },
    )


def test_dyld_library_path_lookups() -> None:
    # Test that DYLD_LIBRARY_PATH can be used to find libs during
    # delocation
    with TempDirWithoutEnvVars("DYLD_LIBRARY_PATH") as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, "subtree")
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        # move libb and confirm that test_lib doesn't work
        hidden_dir = "hidden"
        os.mkdir(hidden_dir)
        new_libb = os.path.join(hidden_dir, os.path.basename(LIBB))
        shutil.move(libb, new_libb)
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.run([test_lib], check=True)
        # Update DYLD_LIBRARY_PATH and confirm that we can now
        # successfully delocate test_lib
        os.environ["DYLD_LIBRARY_PATH"] = hidden_dir
        delocate_path("subtree", "deplibs")
        subprocess.run([test_lib], check=True)


def test_dyld_library_path_beats_basename():
    # type: () -> None
    # Test that we find libraries on DYLD_LIBRARY_PATH before basename
    with TempDirWithoutEnvVars("DYLD_LIBRARY_PATH") as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, "subtree")
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        # Copy liba into a subdirectory
        subdir = os.path.join(subtree, "subdir")
        os.mkdir(subdir)
        new_libb = os.path.join(subdir, os.path.basename(LIBB))
        shutil.copyfile(libb, new_libb)
        # Without updating the environment variable, we find the lib normally
        predicted_lib_location = search_environment_for_lib(libb)
        # tmpdir can end up in /var, and that can be symlinked to
        # /private/var, so we'll use realpath to resolve the two
        assert_equal(predicted_lib_location, os.path.realpath(libb))
        # Updating shows us the new lib
        os.environ["DYLD_LIBRARY_PATH"] = subdir
        predicted_lib_location = search_environment_for_lib(libb)
        assert_equal(predicted_lib_location, realpath(new_libb))


def test_dyld_fallback_library_path_loses_to_basename():
    # type: () -> None
    # Test that we find libraries on basename before DYLD_FALLBACK_LIBRARY_PATH
    with TempDirWithoutEnvVars("DYLD_FALLBACK_LIBRARY_PATH") as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, "subtree")
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        # Copy liba into a subdirectory
        subdir = "subdir"
        os.mkdir(subdir)
        new_libb = os.path.join(subdir, os.path.basename(LIBB))
        shutil.copyfile(libb, new_libb)
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = subdir
        predicted_lib_location = search_environment_for_lib(libb)
        # tmpdir can end up in /var, and that can be symlinked to
        # /private/var, so we'll use realpath to resolve the two
        assert_equal(predicted_lib_location, os.path.realpath(libb))

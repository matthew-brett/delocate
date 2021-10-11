# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
""" Test scripts

If we appear to be running from the development directory, use the scripts in
the top-level folder ``scripts``.  Otherwise try and get the scripts from the
path
"""
from __future__ import absolute_import, division, print_function

import os
import shutil
import subprocess
from os.path import abspath, basename, dirname, exists, isfile
from os.path import join as pjoin
from os.path import realpath, splitext
from typing import Text

from ..tmpdirs import InGivenDirectory, InTemporaryDirectory
from ..tools import dir2zip, set_install_name, zip2dir
from ..wheeltools import InWheel
from .pytest_tools import assert_equal, assert_false, assert_raises, assert_true
from .scriptrunner import ScriptRunner
from .test_delocating import _copy_to, _make_bare_depends, _make_libtree
from .test_fuse import assert_same_tree
from .test_install_names import EXT_LIBS
from .test_wheelies import (
    PLAT_WHEEL,
    PURE_WHEEL,
    WHEEL_PATCH,
    WHEEL_PATCH_BAD,
    PlatWheel,
    _fixed_wheel,
    _rename_module,
    _thin_lib,
    _thin_mod,
)
from .test_wheeltools import (
    EXP_ITEMS,
    EXTRA_EXPS,
    EXTRA_PLATS,
    assert_winfo_similar,
)


def _proc_lines(in_str):
    """Decode `in_string` to str, split lines, strip whitespace

    Remove any empty lines.

    Parameters
    ----------
    in_str : bytes
        Input bytes for splitting, stripping

    Returns
    -------
    out_lines : list
        List of line ``str`` where each line has been stripped of leading and
        trailing whitespace and empty lines have been removed.
    """
    lines = in_str.decode("latin1").splitlines()
    return [line.strip() for line in lines if line.strip() != ""]


lines_runner = ScriptRunner(output_processor=_proc_lines)
run_command = lines_runner.run_command
bytes_runner = ScriptRunner()


DATA_PATH = abspath(pjoin(dirname(__file__), "data"))


def test_listdeps(plat_wheel: PlatWheel) -> None:
    # smokey tests of list dependencies command
    local_libs = {
        "liba.dylib",
        "libb.dylib",
        "libc.dylib",
        "libextfunc2_rpath.dylib",
    }
    # single path, with libs
    with InGivenDirectory(DATA_PATH):
        code, stdout, stderr = run_command(["delocate-listdeps", DATA_PATH])
    assert set(stdout) == local_libs
    assert code == 0
    # single path, no libs
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "pure")
        code, stdout, stderr = run_command(["delocate-listdeps", "pure"])
        assert set(stdout) == set()
        assert code == 0
        # Multiple paths one with libs
        zip2dir(plat_wheel.whl, "plat")
        code, stdout, stderr = run_command(
            ["delocate-listdeps", "pure", "plat"]
        )
        assert stdout == ["pure:", "plat:", plat_wheel.stray_lib]
        assert code == 0
        # With -d flag, get list of dependending modules
        code, stdout, stderr = run_command(
            ["delocate-listdeps", "-d", "pure", "plat"]
        )
        assert stdout == [
            "pure:",
            "plat:",
            plat_wheel.stray_lib + ":",
            pjoin("plat", "fakepkg1", "subpkg", "module2.abi3.so"),
        ]
        assert code == 0

    # With --all flag, get all dependencies
    with InGivenDirectory(DATA_PATH):
        code, stdout, stderr = run_command(
            ["delocate-listdeps", "--all", DATA_PATH]
        )
    rp_ext_libs = set(realpath(L) for L in EXT_LIBS)
    assert set(stdout) == local_libs | rp_ext_libs
    assert code == 0
    # Works on wheels as well
    code, stdout, stderr = run_command(["delocate-listdeps", PURE_WHEEL])
    assert set(stdout) == set()
    code, stdout, stderr = run_command(
        ["delocate-listdeps", PURE_WHEEL, plat_wheel.whl]
    )
    assert stdout == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib,
    ]
    # -d flag (is also --dependency flag)
    m2 = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
    code, stdout, stderr = run_command(
        ["delocate-listdeps", "--depending", PURE_WHEEL, plat_wheel.whl]
    )
    assert stdout == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
    ]
    # Can be used with --all
    code, stdout, stderr = run_command(
        [
            "delocate-listdeps",
            "--all",
            "--depending",
            PURE_WHEEL,
            plat_wheel.whl,
        ]
    )
    assert stdout == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
        EXT_LIBS[1] + ":",
        m2,
        plat_wheel.stray_lib,
    ]


def test_path() -> None:
    # Test path cleaning
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        liba, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree")
        )
        os.makedirs("fakelibs")
        # Make a fake external library to link to
        fake_lib = realpath(_copy_to(liba, "fakelibs", "libfake.dylib"))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree2")
        )
        subprocess.run([test_lib], check=True)
        subprocess.run([stest_lib], check=True)
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # Check it fixes up correctly
        code, stdout, stderr = run_command(
            ["delocate-path", "subtree", "subtree2", "-L", "deplibs"]
        )
        assert len(os.listdir(pjoin("subtree", "deplibs"))) == 0
        # Check fake libary gets copied and delocated
        out_path = pjoin("subtree2", "deplibs")
        assert os.listdir(out_path) == ["libfake.dylib"]


def test_path_dylibs():
    # Test delocate-path with and without dylib extensions
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        out_dypath = pjoin("subtree", "deplibs")
        code, stdout, stderr = run_command(
            ["delocate-path", "subtree", "-L", "deplibs", "-d"]
        )
        assert_equal(len(os.listdir(out_dypath)), 0)
        code, stdout, stderr = run_command(
            ["delocate-path", "subtree", "-L", "deplibs", "--dylibs-only"]
        )
        assert_equal(len(os.listdir(pjoin("subtree", "deplibs"))), 0)
        # Default - does inspect non-dylib files
        code, stdout, stderr = run_command(
            ["delocate-path", "subtree", "-L", "deplibs"]
        )
        assert_equal(os.listdir(out_dypath), ["liba.dylib"])


def _check_wheel(wheel_fname, lib_sdir):
    wheel_fname = abspath(wheel_fname)
    with InTemporaryDirectory():
        zip2dir(wheel_fname, "plat_pkg")
        dylibs = pjoin("plat_pkg", "fakepkg1", lib_sdir)
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ["libextfunc.dylib"])


def test_wheel():
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(["delocate-wheel", fixed_wheel])
        _check_wheel(fixed_wheel, ".dylibs")
        # Make another copy to test another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(
            ["delocate-wheel", "-L", "dynlibs_dir", fixed_wheel]
        )
        _check_wheel(fixed_wheel, "dynlibs_dir")
        # Another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(
            ["delocate-wheel", "-w", "fixed", fixed_wheel]
        )
        _check_wheel(pjoin("fixed", basename(fixed_wheel)), ".dylibs")
        # More than one wheel
        shutil.copy2(fixed_wheel, "wheel_copy.ext")
        code, stdout, stderr = run_command(
            ["delocate-wheel", "-w", "fixed2", fixed_wheel, "wheel_copy.ext"]
        )
        assert_equal(
            stdout,
            ["Fixing: " + name for name in (fixed_wheel, "wheel_copy.ext")],
        )
        _check_wheel(pjoin("fixed2", basename(fixed_wheel)), ".dylibs")
        _check_wheel(pjoin("fixed2", "wheel_copy.ext"), ".dylibs")
        # Verbose - single wheel
        code, stdout, stderr = run_command(
            ["delocate-wheel", "-w", "fixed3", fixed_wheel, "-v"]
        )
        _check_wheel(pjoin("fixed3", basename(fixed_wheel)), ".dylibs")
        wheel_lines1 = [
            "Fixing: " + fixed_wheel,
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert_equal(stdout, wheel_lines1)
        code, stdout, stderr = run_command(
            [
                "delocate-wheel",
                "-v",
                "--wheel-dir",
                "fixed4",
                fixed_wheel,
                "wheel_copy.ext",
            ]
        )
        wheel_lines2 = [
            "Fixing: wheel_copy.ext",
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert_equal(stdout, wheel_lines1 + wheel_lines2)


def test_fix_wheel_dylibs():
    # Check default and non-default search for dynamic libraries
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, "module.other", "test.whl")
        shutil.copyfile("test.whl", "test2.whl")
        # Default is to look in all files and therefore fix
        code, stdout, stderr = run_command(["delocate-wheel", "test.whl"])
        _check_wheel("test.whl", ".dylibs")
        # Can turn this off to only look in dynamic lib exts
        code, stdout, stderr = run_command(
            ["delocate-wheel", "test2.whl", "-d"]
        )
        with InWheel("test2.whl"):  # No fix
            assert_false(exists(pjoin("fakepkg1", ".dylibs")))


def test_fix_wheel_archs():
    # type: () -> None
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Test check of architectures
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        # Fixed wheel, architectures are OK
        code, stdout, stderr = run_command(
            ["delocate-wheel", fixed_wheel, "-k"]
        )
        _check_wheel(fixed_wheel, ".dylibs")
        # Broken with one architecture removed
        archs = set(("x86_64", "arm64"))

        def _fix_break(arch):
            # type: (Text) -> None
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)

        def _fix_break_fix(arch):
            # type: (Text) -> None
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
            _thin_mod(fixed_wheel, arch)

        for arch in archs:
            # Not checked
            _fix_break(arch)
            code, stdout, stderr = run_command(["delocate-wheel", fixed_wheel])
            _check_wheel(fixed_wheel, ".dylibs")
            # Checked
            _fix_break(arch)
            code, stdout, stderr = bytes_runner.run_command(
                ["delocate-wheel", fixed_wheel, "--check-archs"],
                check_code=False,
            )
            assert_false(code == 0)
            stderr_unicode = stderr.decode("latin1").strip()
            assert stderr_unicode.startswith("Traceback")
            assert (
                "DelocationError: Some missing architectures in wheel"
                in stderr_unicode
            )
            assert_equal(stdout.strip(), b"")
            # Checked, verbose
            _fix_break(arch)
            code, stdout, stderr = bytes_runner.run_command(
                ["delocate-wheel", fixed_wheel, "--check-archs", "-v"],
                check_code=False,
            )
            assert_false(code == 0)
            stderr = stderr.decode("latin1").strip()
            assert "Traceback" in stderr
            assert stderr.endswith(
                "DelocationError: Some missing architectures in wheel"
                f"\n{'fakepkg1/subpkg/module2.abi3.so'}"
                f" needs arch {archs.difference([arch]).pop()}"
                f" missing from {stray_lib}"
            )
            stdout_unicode = stdout.decode("latin1").strip()
            assert stdout_unicode == f"Fixing: {fixed_wheel}"
            # Require particular architectures
        both_archs = "arm64,x86_64"
        for ok in ("universal2", "arm64", "x86_64", both_archs):
            _fixed_wheel(tmpdir)
            code, stdout, stderr = run_command(
                ["delocate-wheel", fixed_wheel, "--require-archs=" + ok]
            )
        for arch in archs:
            other_arch = archs.difference([arch]).pop()
            for not_ok in ("intel", both_archs, other_arch):
                _fix_break_fix(arch)
                code, stdout, stderr = run_command(
                    [
                        "delocate-wheel",
                        fixed_wheel,
                        "--require-archs=" + not_ok,
                    ],
                    check_code=False,
                )
                assert_false(code == 0)


def test_fuse_wheels():
    # Some tests for wheel fusing
    with InTemporaryDirectory():
        zip2dir(PLAT_WHEEL, "to_wheel")
        zip2dir(PLAT_WHEEL, "from_wheel")
        dir2zip("to_wheel", "to_wheel.whl")
        dir2zip("from_wheel", "from_wheel.whl")
        code, stdout, stderr = run_command(
            ["delocate-fuse", "to_wheel.whl", "from_wheel.whl"]
        )
        assert_equal(code, 0)
        zip2dir("to_wheel.whl", "to_wheel_fused")
        assert_same_tree("to_wheel_fused", "from_wheel")
        # Test output argument
        os.mkdir("wheels")
        code, stdout, stderr = run_command(
            ["delocate-fuse", "to_wheel.whl", "from_wheel.whl", "-w", "wheels"]
        )
        zip2dir(pjoin("wheels", "to_wheel.whl"), "to_wheel_refused")
        assert_same_tree("to_wheel_refused", "from_wheel")


def test_patch_wheel():
    # Some tests for patching wheel
    with InTemporaryDirectory():
        shutil.copyfile(PURE_WHEEL, "example.whl")
        # Default is to overwrite input
        code, stdout, stderr = run_command(
            ["delocate-patch", "example.whl", WHEEL_PATCH]
        )
        zip2dir("example.whl", "wheel1")
        with open(pjoin("wheel1", "fakepkg2", "__init__.py"), "rt") as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Pass output directory
        shutil.copyfile(PURE_WHEEL, "example.whl")
        code, stdout, stderr = run_command(
            ["delocate-patch", "example.whl", WHEEL_PATCH, "-w", "wheels"]
        )
        zip2dir(pjoin("wheels", "example.whl"), "wheel2")
        with open(pjoin("wheel2", "fakepkg2", "__init__.py"), "rt") as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Bad patch fails
        shutil.copyfile(PURE_WHEEL, "example.whl")
        assert_raises(
            RuntimeError,
            run_command,
            ["delocate-patch", "example.whl", WHEEL_PATCH_BAD],
        )


def test_add_platforms():
    # Check adding platform to wheel name and tag section
    assert_winfo_similar(PLAT_WHEEL, EXP_ITEMS, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Need to specify at least one platform
        assert_raises(
            RuntimeError,
            run_command,
            ["delocate-addplat", PURE_WHEEL, "-w", tmpdir],
        )
        plat_args = ["-p", EXTRA_PLATS[0], "--plat-tag", EXTRA_PLATS[1]]
        # Can't add platforms to a pure wheel
        assert_raises(
            RuntimeError,
            run_command,
            ["delocate-addplat", PURE_WHEEL, "-w", tmpdir] + plat_args,
        )
        assert_false(exists(out_fname))
        # Error raised (as above) unless ``--skip-error`` flag set
        code, stdout, stderr = run_command(
            ["delocate-addplat", PURE_WHEEL, "-w", tmpdir, "-k"] + plat_args
        )
        # Still doesn't do anything though
        assert_false(exists(out_fname))
        # Works for plat_wheel
        out_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],) + EXTRA_PLATS + ("whl",)
        )
        code, stdout, stderr = run_command(
            ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir] + plat_args
        )
        assert_true(isfile(out_fname))
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # If wheel exists (as it does) then raise error
        assert_raises(
            RuntimeError,
            run_command,
            ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir] + plat_args,
        )
        # Unless clobber is set
        code, stdout, stderr = run_command(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir] + plat_args
        )
        # Can also specify platform tags via --osx-ver flags
        code, stdout, stderr = run_command(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir, "-x", "10_9"]
        )
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # Can mix plat_tag and osx_ver
        extra_extra = ("macosx_10_12_universal2", "macosx_10_12_x86_64")
        out_big_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],)
            + EXTRA_PLATS
            + extra_extra
            + ("whl",)
        )
        extra_big_exp = EXTRA_EXPS + [
            ("Tag", "{pyver}-{abi}-" + plat) for plat in extra_extra
        ]
        code, stdout, stderr = run_command(
            [
                "delocate-addplat",
                PLAT_WHEEL,
                "-w",
                tmpdir,
                "-x",
                "10_12",
                "-d",
                "universal2",
            ]
            + plat_args
        )
        assert_winfo_similar(out_big_fname, extra_big_exp)
        # Default is to write into directory of wheel
        os.mkdir("wheels")
        shutil.copy2(PLAT_WHEEL, "wheels")
        local_plat = pjoin("wheels", basename(PLAT_WHEEL))
        local_out = pjoin("wheels", out_fname)
        code, stdout, stderr = run_command(
            ["delocate-addplat", local_plat] + plat_args
        )
        assert_true(exists(local_out))
        # With rm_orig flag, delete original unmodified wheel
        os.unlink(local_out)
        code, stdout, stderr = run_command(
            ["delocate-addplat", "-r", local_plat] + plat_args
        )
        assert_false(exists(local_plat))
        assert_true(exists(local_out))
        # Copy original back again
        shutil.copy2(PLAT_WHEEL, "wheels")
        # If platforms already present, don't write more
        res = sorted(os.listdir("wheels"))
        assert_winfo_similar(local_out, EXTRA_EXPS)
        code, stdout, stderr = run_command(
            ["delocate-addplat", local_out, "--clobber"] + plat_args
        )
        assert_equal(sorted(os.listdir("wheels")), res)
        assert_winfo_similar(local_out, EXTRA_EXPS)
        # The wheel doesn't get deleted output name same as input, as here
        code, stdout, stderr = run_command(
            ["delocate-addplat", local_out, "-r", "--clobber"] + plat_args
        )
        assert_equal(sorted(os.listdir("wheels")), res)
        # But adds WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        assert_raises(
            AssertionError, assert_winfo_similar, local_out, EXTRA_EXPS
        )
        code, stdout, stderr = run_command(
            ["delocate-addplat", local_out, "--clobber"] + plat_args
        )
        assert_equal(sorted(os.listdir("wheels")), res)
        assert_winfo_similar(local_out, EXTRA_EXPS)

# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""Test scripts.

If we appear to be running from the development directory, use the scripts in
the top-level folder ``scripts``.  Otherwise try and get the scripts from the
path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from os.path import basename, exists, realpath, splitext
from os.path import join as pjoin
from pathlib import Path

import pytest
from pytest_console_scripts import ScriptRunner

from ..cmd.common import delocate_parser
from ..tmpdirs import InGivenDirectory, InTemporaryDirectory
from ..tools import dir2zip, get_rpaths, set_install_name, zip2dir
from ..wheeltools import InWheel
from .test_delocating import _copy_to, _make_bare_depends, _make_libtree
from .test_fuse import assert_same_tree
from .test_install_names import EXT_LIBS
from .test_wheelies import (
    PLAT_WHEEL,
    PURE_WHEEL,
    RPATH_WHEEL,
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

try:
    from delocate._version import __version__

    DELOCATE_GENERATOR_HEADER = f"Generator: delocate {__version__}"
except ImportError:
    DELOCATE_GENERATOR_HEADER = "Generator: delocate"

DATA_PATH = (Path(__file__).parent / "data").resolve(strict=True)


def _proc_lines(in_str: str) -> list[str]:
    """Return input split across lines, striping whitespace, without blanks.

    Parameters
    ----------
    in_str : str
        Input for splitting, stripping

    Returns
    -------
    out_lines : list
        List of line ``str`` where each line has been stripped of leading and
        trailing whitespace and empty lines have been removed.
    """
    lines = in_str.splitlines()
    return [line.strip() for line in lines if line.strip() != ""]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_listdeps(plat_wheel: PlatWheel, script_runner: ScriptRunner) -> None:
    # smokey tests of list dependencies command
    local_libs = {
        "liba.dylib",
        "libb.dylib",
        "libc.dylib",
        "libextfunc2_rpath.dylib",
    }
    # single path, with libs
    with InGivenDirectory(DATA_PATH):
        result = script_runner.run(
            "delocate-listdeps", str(DATA_PATH), check=True
        )
    assert set(_proc_lines(result.stdout)) == local_libs
    # single path, no libs
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "pure")
        result = script_runner.run(["delocate-listdeps", "pure"], check=True)
        assert result.stdout.strip() == ""

        # Multiple paths one with libs
        zip2dir(plat_wheel.whl, "plat")
        result = script_runner.run(
            ["delocate-listdeps", "pure", "plat"], check=True
        )
        assert _proc_lines(result.stdout) == [
            "pure:",
            "plat:",
            plat_wheel.stray_lib,
        ]

        # With -d flag, get list of dependending modules
        result = script_runner.run(
            ["delocate-listdeps", "-d", "pure", "plat"], check=True
        )
        assert _proc_lines(result.stdout) == [
            "pure:",
            "plat:",
            plat_wheel.stray_lib + ":",
            str(Path("plat", "fakepkg1", "subpkg", "module2.abi3.so")),
        ]

    # With --all flag, get all dependencies
    with InGivenDirectory(DATA_PATH):
        result = script_runner.run(
            ["delocate-listdeps", "--all", DATA_PATH], check=True
        )
    rp_ext_libs = set(realpath(L) for L in EXT_LIBS)
    assert set(_proc_lines(result.stdout)) == local_libs | rp_ext_libs

    # Works on wheels as well
    result = script_runner.run(["delocate-listdeps", PURE_WHEEL], check=True)
    assert result.stdout.strip() == ""
    result = script_runner.run(
        ["delocate-listdeps", PURE_WHEEL, plat_wheel.whl], check=True
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib,
    ]

    # -d flag (is also --dependency flag)
    m2 = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
    result = script_runner.run(
        ["delocate-listdeps", "--depending", PURE_WHEEL, plat_wheel.whl],
        check=True,
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
    ]

    # Can be used with --all
    result = script_runner.run(
        [
            "delocate-listdeps",
            "--all",
            "--depending",
            PURE_WHEEL,
            plat_wheel.whl,
        ],
        check=True,
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
        EXT_LIBS[1] + ":",
        m2,
        plat_wheel.stray_lib,
    ]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Runs macOS executable."
)
def test_path(script_runner: ScriptRunner) -> None:
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
        script_runner.run(
            ["delocate-path", "subtree", "subtree2", "-L", "deplibs"],
            check=True,
        )
        assert len(os.listdir(Path("subtree", "deplibs"))) == 0
        # Check fake libary gets copied and delocated
        out_path = Path("subtree2", "deplibs")
        assert os.listdir(out_path) == ["libfake.dylib"]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_path_dylibs(script_runner: ScriptRunner) -> None:
    # Test delocate-path with and without dylib extensions
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        out_dypath = Path("subtree", "deplibs")
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs", "-d"], check=True
        )
        assert len(os.listdir(out_dypath)) == 0
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs", "--dylibs-only"],
            check=True,
        )
        assert len(os.listdir(Path("subtree", "deplibs"))) == 0
        # Default - does inspect non-dylib files
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs"], check=True
        )
        assert os.listdir(out_dypath) == ["liba.dylib"]


def _check_wheel(wheel_fname: str | Path, lib_sdir: str | Path) -> None:
    wheel_fname = Path(wheel_fname).resolve(strict=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        plat_pkg_path = Path(temp_dir, "plat_pkg")
        zip2dir(wheel_fname, plat_pkg_path)
        dylibs = Path(plat_pkg_path, "fakepkg1", lib_sdir)
        assert dylibs.exists()
        assert os.listdir(dylibs) == ["libextfunc.dylib"]
        (wheel_info,) = plat_pkg_path.glob("*.dist-info/WHEEL")
        assert DELOCATE_GENERATOR_HEADER in wheel_info.read_text()


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_wheel(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(["delocate-wheel", fixed_wheel], check=True)
        _check_wheel(fixed_wheel, ".dylibs")
        # Make another copy to test another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(
            ["delocate-wheel", "-L", "dynlibs_dir", fixed_wheel], check=True
        )
        _check_wheel(fixed_wheel, "dynlibs_dir")
        # Another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(
            ["delocate-wheel", "-w", "fixed", fixed_wheel], check=True
        )
        _check_wheel(Path("fixed", Path(fixed_wheel).name), ".dylibs")
        # More than one wheel
        copy_name = "fakepkg1_copy-1.0-cp36-abi3-macosx_10_9_universal2.whl"
        shutil.copy2(fixed_wheel, copy_name)
        result = script_runner.run(
            ["delocate-wheel", "-w", "fixed2", fixed_wheel, copy_name],
            check=True,
        )
        assert _proc_lines(result.stdout) == [
            "Fixing: " + name for name in (fixed_wheel, copy_name)
        ]
        _check_wheel(Path("fixed2", Path(fixed_wheel).name), ".dylibs")
        _check_wheel(Path("fixed2", copy_name), ".dylibs")

        # Verbose - single wheel
        result = script_runner.run(
            ["delocate-wheel", "-w", "fixed3", fixed_wheel, "-v"], check=True
        )
        _check_wheel(Path("fixed3", Path(fixed_wheel).name), ".dylibs")
        wheel_lines1 = [
            "Fixing: " + fixed_wheel,
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert _proc_lines(result.stdout) == wheel_lines1

        result = script_runner.run(
            [
                "delocate-wheel",
                "-v",
                "--wheel-dir",
                "fixed4",
                fixed_wheel,
                copy_name,
            ],
            check=True,
        )
        wheel_lines2 = [
            f"Fixing: {copy_name}",
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert _proc_lines(result.stdout) == wheel_lines1 + wheel_lines2


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_fix_wheel_dylibs(script_runner: ScriptRunner, tmp_path: Path) -> None:
    # Check default and non-default search for dynamic libraries
    fixed_wheel, stray_lib = _fixed_wheel(tmp_path)
    test1_name = (
        tmp_path / "fakepkg1_test-1.0-cp36-abi3-macosx_10_9_universal2.whl"
    )
    test2_name = (
        tmp_path / "fakepkg1_test2-1.0-cp36-abi3-macosx_10_9_universal2.whl"
    )
    _rename_module(fixed_wheel, "module.other", test1_name)
    shutil.copyfile(test1_name, test2_name)
    # Default is to look in all files and therefore fix
    script_runner.run(["delocate-wheel", test1_name], check=True)
    _check_wheel(test1_name, ".dylibs")
    # Can turn this off to only look in dynamic lib exts
    script_runner.run(["delocate-wheel", test2_name, "-d"], check=True)
    with InWheel(test2_name):  # No fix
        assert not Path("fakepkg1", ".dylibs").exists()


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_fix_wheel_archs(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Test check of architectures
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        # Fixed wheel, architectures are OK
        script_runner.run(["delocate-wheel", fixed_wheel, "-k"], check=True)
        _check_wheel(fixed_wheel, ".dylibs")
        # Broken with one architecture removed
        archs = set(("x86_64", "arm64"))

        def _fix_break(arch: str) -> None:
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)

        def _fix_break_fix(arch: str) -> None:
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
            _thin_mod(fixed_wheel, arch)

        for arch in archs:
            # Not checked
            _fix_break(arch)
            script_runner.run(["delocate-wheel", fixed_wheel], check=True)
            _check_wheel(fixed_wheel, ".dylibs")
            # Checked
            _fix_break(arch)
            result = script_runner.run(
                ["delocate-wheel", fixed_wheel, "--check-archs"]
            )
            assert result.returncode != 0
            assert result.stderr.startswith("Traceback")
            assert (
                "DelocationError: Some missing architectures in wheel"
                in result.stderr
            )
            assert result.stdout.strip() == ""
            # Checked, verbose
            _fix_break(arch)
            result = script_runner.run(
                ["delocate-wheel", fixed_wheel, "--check-archs", "-v"]
            )
            assert result.returncode != 0
            assert "Traceback" in result.stderr
            assert result.stderr.endswith(
                "DelocationError: Some missing architectures in wheel"
                f"\n{'fakepkg1/subpkg/module2.abi3.so'}"
                f" needs arch {archs.difference([arch]).pop()}"
                f" missing from {stray_lib}\n"
            )
            assert result.stdout == f"Fixing: {fixed_wheel}\n"
            # Require particular architectures
        both_archs = "arm64,x86_64"
        for ok in ("universal2", "arm64", "x86_64", both_archs):
            _fixed_wheel(tmpdir)
            script_runner.run(
                ["delocate-wheel", fixed_wheel, "--require-archs=" + ok],
                check=True,
            )
        for arch in archs:
            other_arch = archs.difference([arch]).pop()
            for not_ok in ("intel", both_archs, other_arch):
                _fix_break_fix(arch)
                result = script_runner.run(
                    [
                        "delocate-wheel",
                        fixed_wheel,
                        "--require-archs=" + not_ok,
                    ],
                )
                assert result.returncode != 0


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="requires lipo"
)
def test_fuse_wheels(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fusing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        # Wheels need proper wheel filename for delocate-merge
        to_wheel = temp_path / f"to_{Path(PLAT_WHEEL).name}"
        from_wheel = temp_path / f"from_{Path(PLAT_WHEEL).name}"
        zip2dir(PLAT_WHEEL, temp_path / "to_wheel")
        zip2dir(PLAT_WHEEL, temp_path / "from_wheel")
        dir2zip(temp_path / "to_wheel", to_wheel)
        dir2zip(temp_path / "from_wheel", from_wheel)
        # Make sure delocate-fuse returns a non-zero exit code, it is no longer
        # supported
        result = script_runner.run(
            ["delocate-fuse", to_wheel, from_wheel], cwd=temp_path
        )
        assert result.returncode != 0

        script_runner.run(
            ["delocate-merge", to_wheel, from_wheel], check=True, cwd=temp_path
        )
        zip2dir(to_wheel, temp_path / "to_wheel_fused")
        assert_same_tree(
            temp_path / "to_wheel_fused",
            temp_path / "from_wheel",
            updated_metadata=True,
        )
        # Test output argument
        script_runner.run(
            ["delocate-merge", to_wheel, from_wheel, "-w", "wheels"],
            check=True,
            cwd=temp_path,
        )
        zip2dir(
            Path(temp_path, "wheels", to_wheel), temp_path / "to_wheel_refused"
        )
        (wheel_info,) = Path(temp_path, "to_wheel_refused").glob(
            "*.dist-info/WHEEL"
        )
        assert DELOCATE_GENERATOR_HEADER in wheel_info.read_text()
        assert_same_tree(
            temp_path / "to_wheel_refused",
            temp_path / "from_wheel",
            updated_metadata=True,
        )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform == "win32", reason="Can't run scripts."
)
def test_patch_wheel(script_runner: ScriptRunner) -> None:
    # Some tests for patching wheel
    with InTemporaryDirectory():
        shutil.copyfile(PURE_WHEEL, "example.whl")
        # Default is to overwrite input
        script_runner.run(
            ["delocate-patch", "-v", "example.whl", WHEEL_PATCH], check=True
        )
        zip2dir("example.whl", "wheel1")
        assert (
            Path("wheel1", "fakepkg2", "__init__.py").read_text()
            == 'print("Am in init")\n'
        )
        # Pass output directory
        shutil.copyfile(PURE_WHEEL, "example.whl")
        script_runner.run(
            ["delocate-patch", "example.whl", WHEEL_PATCH, "-w", "wheels"],
            check=True,
        )
        zip2dir(pjoin("wheels", "example.whl"), "wheel2")
        assert (
            Path("wheel2", "fakepkg2", "__init__.py").read_text()
            == 'print("Am in init")\n'
        )
        # Bad patch fails
        shutil.copyfile(PURE_WHEEL, "example.whl")
        result = script_runner.run(
            ["delocate-patch", "example.whl", WHEEL_PATCH_BAD]
        )
        assert result.returncode != 0


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform == "win32", reason="Can't run scripts."
)
def test_add_platforms(script_runner: ScriptRunner) -> None:
    # Check adding platform to wheel name and tag section
    assert_winfo_similar(PLAT_WHEEL, EXP_ITEMS, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Need to specify at least one platform
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PURE_WHEEL, "-w", tmpdir], check=True
            )
        plat_args = ("-p", EXTRA_PLATS[0], "--plat-tag", EXTRA_PLATS[1])
        # Can't add platforms to a pure wheel
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PURE_WHEEL, "-w", tmpdir, *plat_args],
                check=True,
            )
        assert not exists(out_fname)
        # Error raised (as above) unless ``--skip-error`` flag set
        script_runner.run(
            ["delocate-addplat", PURE_WHEEL, "-w", tmpdir, "-k", *plat_args],
            check=True,
        )
        # Still doesn't do anything though
        assert not exists(out_fname)
        # Works for plat_wheel
        out_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],) + EXTRA_PLATS + ("whl",)
        )
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir, *plat_args],
            check=True,
        )
        assert Path(out_fname).is_file()
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # If wheel exists (as it does) then fail
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir, *plat_args],
                check=True,
            )
        # Unless clobber is set
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir, *plat_args],
            check=True,
        )
        # Can also specify platform tags via --osx-ver flags
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir, "-x", "10_9"],
            check=True,
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
        script_runner.run(
            [
                "delocate-addplat",
                PLAT_WHEEL,
                "-w",
                tmpdir,
                "-x",
                "10_12",
                "-d",
                "universal2",
                *plat_args,
            ],
            check=True,
        )
        assert_winfo_similar(out_big_fname, extra_big_exp)
        # Default is to write into directory of wheel
        os.mkdir("wheels")
        shutil.copy2(PLAT_WHEEL, "wheels")
        local_plat = pjoin("wheels", basename(PLAT_WHEEL))
        local_out = pjoin("wheels", out_fname)
        script_runner.run(
            ["delocate-addplat", local_plat, *plat_args], check=True
        )
        assert exists(local_out)
        # With rm_orig flag, delete original unmodified wheel
        os.unlink(local_out)
        script_runner.run(
            ["delocate-addplat", "-r", local_plat, *plat_args], check=True
        )
        assert not exists(local_plat)
        assert exists(local_out)
        # Copy original back again
        shutil.copy2(PLAT_WHEEL, "wheels")
        # If platforms already present, don't write more
        res = sorted(os.listdir("wheels"))
        assert_winfo_similar(local_out, EXTRA_EXPS)
        script_runner.run(
            ["delocate-addplat", local_out, "--clobber", *plat_args], check=True
        )
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(local_out, EXTRA_EXPS)
        # The wheel doesn't get deleted output name same as input, as here
        script_runner.run(
            ["delocate-addplat", local_out, "-r", "--clobber", *plat_args],
            check=True,
        )
        assert sorted(os.listdir("wheels")) == res
        # But adds WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        with pytest.raises(AssertionError):
            assert_winfo_similar(local_out, EXTRA_EXPS)
        script_runner.run(
            ["delocate-addplat", local_out, "--clobber", *plat_args], check=True
        )
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(local_out, EXTRA_EXPS)
        assert_winfo_similar(local_out, EXTRA_EXPS)


@pytest.mark.xfail(sys.platform != "darwin", reason="Needs macOS linkage.")
def test_fix_wheel_with_excluded_dylibs(
    script_runner: ScriptRunner, tmp_path: Path
) -> None:
    fixed_wheel, stray_lib = _fixed_wheel(tmp_path)
    test1_name = (
        tmp_path / "fakepkg1_test-1.0-cp36-abi3-macosx_10_9_universal2.whl"
    )
    test2_name = (
        tmp_path / "fakepkg1_test2-1.0-cp36-abi3-macosx_10_9_universal2.whl"
    )

    _rename_module(fixed_wheel, "module.other", test1_name)
    shutil.copyfile(test1_name, test2_name)
    # We exclude the stray library so it shouldn't be present in the wheel
    result = script_runner.run(
        ["delocate-wheel", "-vv", "-e", "extfunc", test1_name], check=True
    )
    assert "libextfunc.dylib excluded" in result.stderr
    with InWheel(test1_name):
        assert not Path("plat_pkg/fakepkg1/.dylibs").exists()
    # We exclude a library that does not exist so we should behave normally
    script_runner.run(
        ["delocate-wheel", "-e", "doesnotexist", test2_name], check=True
    )
    _check_wheel(test2_name, ".dylibs")


def test_sanitize_rpaths_flag() -> None:
    args = delocate_parser.parse_args([])
    assert args.sanitize_rpaths
    args = delocate_parser.parse_args(["--sanitize-rpaths"])
    assert args.sanitize_rpaths
    args = delocate_parser.parse_args(["--no-sanitize-rpaths"])
    assert not args.sanitize_rpaths


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
@pytest.mark.parametrize("sanitize_rpaths", [True, False])
def test_sanitize_command(
    tmp_path: Path, script_runner: ScriptRunner, sanitize_rpaths: bool
) -> None:
    unpack_dir = tmp_path / "unpack"
    zip2dir(RPATH_WHEEL, unpack_dir)
    assert "libs/" in set(
        get_rpaths(str(unpack_dir / "fakepkg/subpkg/module2.abi3.so"))
    )
    rpath_wheel = tmp_path / "example-1.0-cp37-abi3-macosx_10_9_x86_64.whl"
    shutil.copyfile(RPATH_WHEEL, rpath_wheel)
    libs_path = tmp_path / "libs"
    libs_path.mkdir()
    shutil.copy(DATA_PATH / "libextfunc_rpath.dylib", libs_path)
    shutil.copy(DATA_PATH / "libextfunc2_rpath.dylib", libs_path)
    cmd = ["delocate-wheel", "-vv"]
    if not sanitize_rpaths:
        cmd.append("--no-sanitize-rpaths")
    result = script_runner.run(
        cmd + [rpath_wheel],
        check=True,
        cwd=tmp_path,
    )
    if sanitize_rpaths:
        assert "Sanitize: Deleting rpath 'libs/' from" in result.stderr
    else:
        assert "Deleting rpath" not in result.stderr

    unpack_dir = tmp_path / "unpack"
    zip2dir(rpath_wheel, unpack_dir)
    rpaths = set(get_rpaths(str(unpack_dir / "fakepkg/subpkg/module2.abi3.so")))
    if sanitize_rpaths:
        assert "libs/" not in rpaths
    else:
        assert "libs/" in rpaths


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_glob(
    tmp_path: Path, plat_wheel: PlatWheel, script_runner: ScriptRunner
) -> None:
    # Test implicit globbing by passing "*.whl" without shell=True
    script_runner.run(["delocate-listdeps", "*.whl"], check=True, cwd=tmp_path)
    zip2dir(plat_wheel.whl, tmp_path / "plat")

    result = script_runner.run(
        ["delocate-wheel", "*.whl", "-v"], check=True, cwd=tmp_path
    )
    assert Path(plat_wheel.whl).name in result.stdout
    assert "*.whl" not in result.stdout
    assert not Path(tmp_path, "*.whl").exists()

    Path(plat_wheel.whl).unlink()
    result = script_runner.run(["delocate-wheel", "*.whl"], cwd=tmp_path)
    assert result.returncode == 1
    assert "FileNotFoundError:" in result.stderr

    script_runner.run(["delocate-path", "*/"], check=True, cwd=tmp_path)


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_fix_name(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    shutil.copy(
        DATA_PATH / "liba_12.dylib", tmp_path / "plat/fakepkg1/liba_12.dylib"
    )
    dir2zip(tmp_path / "plat", plat_wheel.whl)
    script_runner.run(
        ["delocate-wheel", plat_wheel.whl], check=True, cwd=tmp_path
    )
    assert (tmp_path / "plat-1.0-cp311-cp311-macosx_12_0_x86_64.whl").exists()
    assert not Path(plat_wheel.whl).exists()
    with InWheel(
        tmp_path / "plat-1.0-cp311-cp311-macosx_12_0_x86_64.whl"
    ) as wheel:
        with open(pjoin(wheel, "fakepkg1-1.0.dist-info", "WHEEL")) as f:
            assert "macosx_12_0_x86_64" in f.read()


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_verify_name(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    whl_10_6 = tmp_path / "plat-1.0-cp311-cp311-macosx_10_6_x86_64.whl"
    dir2zip(tmp_path / "plat", whl_10_6)
    result = script_runner.run(
        ["delocate-wheel", whl_10_6, "--require-target-macos-version", "10.6"],
        check=False,
        cwd=tmp_path,
        print_result=False,
    )
    assert result.returncode != 0
    assert "Library dependencies do not satisfy target MacOS" in result.stderr
    assert "module2.abi3.so has a minimum target of 10.9" in result.stderr


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_verify_name_universal2_ok(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    shutil.copy(
        DATA_PATH / "libam1.dylib", tmp_path / "plat/fakepkg1/libam1.dylib"
    )
    whl_10_9 = tmp_path / "plat-1.0-cp311-cp311-macosx_10_9_universal2.whl"
    dir2zip(tmp_path / "plat", whl_10_9)
    script_runner.run(
        ["delocate-wheel", whl_10_9, "--require-target-macos-version", "10.9"],
        check=True,
        cwd=tmp_path,
    )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_verify_name_universal_ok(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    shutil.copy(
        DATA_PATH / "np-1.6.0_intel_lib__compiled_base.so",
        tmp_path / "plat/fakepkg1/np-1.6.0_intel_lib__compiled_base.so",
    )
    whl_10_9 = tmp_path / "plat-1.0-cp311-cp311-macosx_10_9_intel.whl"
    dir2zip(tmp_path / "plat", whl_10_9)
    script_runner.run(
        [
            "delocate-wheel",
            whl_10_9,
            "--require-target-macos-version",
            "10.9",
            "--ignore-missing-dependencies",
        ],
        check=True,
        cwd=tmp_path,
    )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_missing_architecture(
    plat_wheel: PlatWheel,
    script_runner: ScriptRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutil.copy(
        plat_wheel.whl,
        tmp_path / "plat2-1.0-cp311-cp311-macosx_10_9_intel.whl",
    )
    result = script_runner.run(
        [
            "delocate-wheel",
            tmp_path / "plat2-1.0-cp311-cp311-macosx_10_9_intel.whl",
        ],
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert (
        "Failed to find any binary with the required architecture: 'i386'"
        in result.stderr
    )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_verify_name_universal2_verify_crash(
    plat_wheel: PlatWheel,
    script_runner: ScriptRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    shutil.copy(
        DATA_PATH / "libam1_12.dylib",
        tmp_path / "plat" / "fakepkg1" / "libam1.dylib",
    )
    whl_10_9 = tmp_path / "plat2-1.0-cp311-cp311-macosx_10_9_universal2.whl"
    dir2zip(tmp_path / "plat", whl_10_9)
    result = script_runner.run(
        ["delocate-wheel", whl_10_9, "--require-target-macos-version", "10.9"],
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "Library dependencies do not satisfy target MacOS" in result.stderr
    assert "libam1.dylib has a minimum target of 12.0" in result.stderr
    assert "MACOSX_DEPLOYMENT_TARGET=12.0" in result.stderr


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_verify_name_universal2_verify_crash_env_var(
    plat_wheel: PlatWheel,
    script_runner: ScriptRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip2dir(plat_wheel.whl, tmp_path / "plat")
    shutil.copy(
        DATA_PATH / "libam1_12.dylib",
        tmp_path / "plat" / "fakepkg1" / "libam1.dylib",
    )
    whl_10_9 = tmp_path / "plat2-1.0-cp311-cp311-macosx_10_9_universal2.whl"
    dir2zip(tmp_path / "plat", whl_10_9)

    result = script_runner.run(
        ["delocate-wheel", whl_10_9],
        check=False,
        cwd=tmp_path,
        env={**os.environ, "MACOSX_DEPLOYMENT_TARGET": "10.9"},
    )
    assert result.returncode != 0
    assert "Library dependencies do not satisfy target MacOS" in result.stderr
    assert "libam1.dylib has a minimum target of 12.0" in result.stderr
    assert "module2.abi3.so has a minimum target of 11.0" not in result.stderr
    assert "MACOSX_DEPLOYMENT_TARGET=12.0" in result.stderr


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_macos_release_minor_version(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    script_runner.run(
        ["delocate-wheel", plat_wheel.whl, "-vv"],
        env={**os.environ, "MACOSX_DEPLOYMENT_TARGET": "13.1"},
        check=True,
    )

    # Should create a 13.0 wheel instead of the requested 13.1
    assert {tmp_path / "plat-1.0-cp311-cp311-macosx_13_0_x86_64.whl"} == set(
        file for file in tmp_path.iterdir() if file.suffix == ".whl"
    )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_delocate_wheel_macos_release_version_warning(
    plat_wheel: PlatWheel, script_runner: ScriptRunner, tmp_path: Path
) -> None:
    with InWheel(plat_wheel.whl, plat_wheel.whl) as wheel_tmp_path:
        shutil.copy(
            DATA_PATH / "liba_12_1.dylib",  # macOS library targeting 12.1
            Path(wheel_tmp_path, "fakepkg1/"),
        )

    result = script_runner.run(
        ["delocate-wheel", plat_wheel.whl, "-vv"], check=True
    )

    assert "will be tagged as supporting macOS 12 (x86_64)" in result.stderr
    assert "will not support macOS versions older than 12.1" in result.stderr

    # Should create a 12.0 wheel instead of 12.1
    assert {tmp_path / "plat-1.0-cp311-cp311-macosx_12_0_x86_64.whl"} == set(
        file for file in tmp_path.iterdir() if file.suffix == ".whl"
    )

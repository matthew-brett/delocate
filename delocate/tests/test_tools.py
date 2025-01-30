"""Test tools module."""

import os
import shutil
import stat
import subprocess
import sys
from os.path import dirname
from os.path import join as pjoin
from pathlib import Path

import pytest

from ..tmpdirs import InTemporaryDirectory
from ..tools import (
    _get_install_ids,
    _get_install_names,
    _get_rpaths,
    _is_macho_file,
    add_rpath,
    chmod_perms,
    cmp_contents,
    dir2zip,
    ensure_permissions,
    ensure_writable,
    find_package_dirs,
    get_archs,
    parse_install_name,
    replace_signature,
    set_install_id,
    set_install_name,
    validate_signature,
    zip2dir,
)
from .pytest_tools import assert_equal, assert_false, assert_raises, assert_true
from .test_install_names import LIBC, LIBSTDCXX

DATA_PATH = pjoin(dirname(__file__), "data")
LIBM1 = pjoin(DATA_PATH, "libam1.dylib")
LIBM1_ARCH = pjoin(DATA_PATH, "libam1-arch.dylib")
LIB64 = pjoin(DATA_PATH, "liba.dylib")
LIBBOTH = pjoin(DATA_PATH, "liba_both.dylib")
LIB64A = pjoin(DATA_PATH, "liba.a")
ARCH_64 = frozenset(["x86_64"])
ARCH_M1 = frozenset(["arm64"])
ARCH_BOTH = ARCH_64 | ARCH_M1
ARCH_32 = frozenset(["i386"])


@pytest.mark.xfail(sys.platform == "win32", reason="Needs chmod.")
def test_ensure_permissions():
    # Test decorator to ensure permissions
    with InTemporaryDirectory():
        # Write, set zero permissions
        sts = {}
        for fname, contents in (
            ("test.read", "A line\n"),
            ("test.write", "B line"),
        ):
            with open(fname, "w") as fobj:
                fobj.write(contents)
            os.chmod(fname, 0)
            sts[fname] = chmod_perms(fname)

        def read_file(fname):
            with open(fname) as fobj:
                contents = fobj.read()
            return contents

        fixed_read_file = ensure_permissions(stat.S_IRUSR)(read_file)
        non_read_file = ensure_permissions(stat.S_IWUSR)(read_file)

        def write_file(fname, contents):
            with open(fname, "w") as fobj:
                fobj.write(contents)

        fixed_write_file = ensure_permissions(stat.S_IWUSR)(write_file)
        non_write_file = ensure_permissions(stat.S_IRUSR)(write_file)

        # Read fails with default, no permissions
        assert_raises(IOError, read_file, "test.read")
        # Write fails with default, no permissions
        assert_raises(IOError, write_file, "test.write", "continues")
        # Read fails with wrong permissions
        assert_raises(IOError, non_read_file, "test.read")
        # Write fails with wrong permissions
        assert_raises(IOError, non_write_file, "test.write", "continues")
        # Read succeeds with fixed function
        assert_equal(fixed_read_file("test.read"), "A line\n")
        # Write fails, no permissions
        assert_raises(IOError, non_write_file, "test.write", "continues")
        # Write succeeds with fixed function
        fixed_write_file("test.write", "continues")
        assert_equal(fixed_read_file("test.write"), "continues")
        # Permissions are as before
        for fname, st in sts.items():
            assert_equal(chmod_perms(fname), st)


@pytest.mark.xfail(sys.platform == "win32", reason="Needs chmod.")
def test_ensure_writable():
    # Test ensure writable decorator
    with InTemporaryDirectory():
        with open("test.bin", "w") as fobj:
            fobj.write("A line\n")
        # Set to user rw, else r
        os.chmod("test.bin", 0o644)
        st = os.stat("test.bin")

        @ensure_writable
        def foo(fname):
            pass

        foo("test.bin")
        assert_equal(os.stat("test.bin"), st)
        # No-one can write
        os.chmod("test.bin", 0o444)
        st = os.stat("test.bin")
        foo("test.bin")
        assert_equal(os.stat("test.bin"), st)


def test_parse_install_name() -> None:
    # otool on versions previous to Catalina
    line0 = (
        "/System/Library/Frameworks/QuartzCore.framework/Versions/A/QuartzCore "
        "(compatibility version 1.2.0, current version 1.11.0)"
    )
    name, cpver, cuver = (
        "/System/Library/Frameworks/QuartzCore.framework/Versions/A/QuartzCore",
        "1.2.0",
        "1.11.0",
    )
    assert parse_install_name(line0) == (name, cpver, cuver)
    # otool on Catalina
    line1 = (
        "/System/Library/Frameworks/QuartzCore.framework/Versions/A/QuartzCore "
        "(compatibility version 1.2.0, current version 1.11.0, weak)"
    )
    assert parse_install_name(line1) == (name, cpver, cuver)

    # Test bad input.
    with pytest.raises(ValueError, match="Could not parse.*bad-str"):
        parse_install_name("bad-str")


def _write_file(filename, contents):
    with open(filename, "w") as fobj:
        fobj.write(contents)


@pytest.mark.skipif(sys.platform == "win32", reason="Tests Unix permissions")
def test_zip2() -> None:
    # Test utilities to unzip and zip up
    with InTemporaryDirectory():
        os.mkdir("a_dir")
        os.mkdir("zips")
        _write_file(pjoin("a_dir", "file1.txt"), "File one")
        s_dir = pjoin("a_dir", "s_dir")
        os.mkdir(s_dir)
        _write_file(pjoin(s_dir, "file2.txt"), "File two")
        zip_fname = pjoin("zips", "my.zip")
        dir2zip("a_dir", zip_fname)
        zip2dir(zip_fname, "another_dir")
        assert set(os.listdir("another_dir")) == {"file1.txt", "s_dir"}
        assert set(os.listdir(pjoin("another_dir", "s_dir"))) == {"file2.txt"}
        # Try zipping from a subdirectory, with a different extension
        dir2zip(s_dir, "another.ext")
        # Remove original tree just to be sure
        shutil.rmtree("a_dir")
        zip2dir("another.ext", "third_dir")
        assert set(os.listdir("third_dir")) == {"file2.txt"}
        # Check permissions kept in zip unzip cycle
        os.mkdir("a_dir")
        permissions = stat.S_IRUSR | stat.S_IWGRP | stat.S_IXGRP
        fname = pjoin("a_dir", "permitted_file")
        _write_file(fname, "Some script or something")
        os.chmod(fname, permissions)
        dir2zip("a_dir", "test.zip")
        zip2dir("test.zip", "another_dir")
        out_fname = pjoin("another_dir", "permitted_file")
        assert os.stat(out_fname).st_mode & 0o777 == permissions


def test_find_package_dirs():
    # Test utility for finding package directories
    with InTemporaryDirectory():
        os.mkdir("to_test")
        a_dir = pjoin("to_test", "a_dir")
        b_dir = pjoin("to_test", "b_dir")
        c_dir = pjoin("to_test", "c_dir")
        for dir in (a_dir, b_dir, c_dir):
            os.mkdir(dir)
        assert_equal(find_package_dirs("to_test"), set([]))
        _write_file(pjoin(a_dir, "__init__.py"), "# a package")
        assert_equal(find_package_dirs("to_test"), {a_dir})
        _write_file(pjoin(c_dir, "__init__.py"), "# another package")
        assert_equal(find_package_dirs("to_test"), {a_dir, c_dir})
        # Not recursive
        assert_equal(find_package_dirs("."), set())
        _write_file(pjoin("to_test", "__init__.py"), "# base package")
        # Also - strips '.' for current directory
        assert_equal(find_package_dirs("."), {"to_test"})


def test_cmp_contents():
    # Binary compare of filenames
    assert_true(cmp_contents(__file__, __file__))
    with InTemporaryDirectory():
        with open("first", "wb") as fobj:
            fobj.write(b"abc\x00\x10\x13\x10")
        with open("second", "wb") as fobj:
            fobj.write(b"abc\x00\x10\x13\x11")
        assert_false(cmp_contents("first", "second"))
        with open("third", "wb") as fobj:
            fobj.write(b"abc\x00\x10\x13\x10")
        assert_true(cmp_contents("first", "third"))
        with open("fourth", "wb") as fobj:
            fobj.write(b"abc\x00\x10\x13\x10\x00")
        assert_false(cmp_contents("first", "fourth"))


@pytest.mark.xfail(sys.platform != "darwin", reason="Needs lipo.")
def test_get_archs() -> None:
    # Test routine to get architecture types from file
    assert get_archs(LIBM1) == ARCH_M1
    assert get_archs(LIBM1_ARCH) == ARCH_M1
    assert get_archs(LIB64) == ARCH_64
    assert get_archs(LIB64A) == ARCH_64
    assert get_archs(LIBBOTH) == ARCH_BOTH
    with pytest.raises(FileNotFoundError):
        get_archs("/nonexistent_file")


@pytest.mark.xfail(sys.platform != "darwin", reason="Needs codesign.")
def test_validate_signature() -> None:
    # Fully test the validate_signature tool
    def check_signature(filename: str) -> None:
        """Raise CalledProcessError if the signature can not be verified."""
        subprocess.run(["codesign", "--verify", filename], check=True)

    with InTemporaryDirectory():
        # Copy a binary file to test with, any binary file would work
        shutil.copyfile(LIBBOTH, "libcopy")

        # validate_signature does not add missing signatures
        validate_signature("libcopy")

        # codesign should raise an error (missing signature)
        with pytest.raises(subprocess.CalledProcessError):
            check_signature("libcopy")

        replace_signature("libcopy", "-")  # Force this file to be signed
        validate_signature("libcopy")  # Cover the `is already valid` code path

        check_signature("libcopy")  # codesign now accepts the file

        # Alter the contents of this file, this will invalidate the signature
        add_rpath("libcopy", "/dummy/path", ad_hoc_sign=False)

        # codesign should raise a new error (invalid signature)
        with pytest.raises(subprocess.CalledProcessError):
            check_signature("libcopy")

        validate_signature("libcopy")  # Replace the broken signature
        check_signature("libcopy")

        # Alter the contents of this file, check that by default the file
        # is signed with an ad-hoc signature
        add_rpath("libcopy", "/dummy/path2")
        check_signature("libcopy")

        set_install_id("libcopy", "libcopy-name")
        check_signature("libcopy")

        set_install_name("libcopy", LIBSTDCXX, "/usr/lib/libstdc++.7.dylib")
        check_signature("libcopy")

        # check that altering the contents without ad-hoc sign invalidates
        # signatures
        set_install_id("libcopy", "libcopy-name2", ad_hoc_sign=False)
        with pytest.raises(subprocess.CalledProcessError):
            check_signature("libcopy")

        set_install_name(
            "libcopy",
            "/usr/lib/libstdc++.7.dylib",
            "/usr/lib/libstdc++.8.dylib",
            ad_hoc_sign=False,
        )
        with pytest.raises(subprocess.CalledProcessError):
            check_signature("libcopy")


def test_is_macho_file() -> None:
    MACHO_FILES = frozenset(
        filename
        for filename in os.listdir(DATA_PATH)
        if filename.endswith((".o", ".dylib", ".so", "test-lib"))
    )

    for filename in os.listdir(DATA_PATH):
        path = pjoin(DATA_PATH, filename)
        if not os.path.isfile(path):
            continue
        assert_equal(_is_macho_file(path), filename in MACHO_FILES)


@pytest.mark.xfail(sys.platform != "darwin", reason="Needs otool.")
def test_archive_member(tmp_path: Path) -> None:
    # Tools should always take a trailing parentheses as a literal file path
    lib_path = Path(tmp_path, "libc(member)")
    shutil.copyfile(LIBC, lib_path)
    assert _get_install_names(lib_path) == {
        "": [
            "liba.dylib",
            "libb.dylib",
            "/usr/lib/libc++.1.dylib",
            "/usr/lib/libSystem.B.dylib",
        ]
    }
    assert _get_install_ids(lib_path) == {"": "libc.dylib"}
    assert _get_rpaths(lib_path) == {"": []}

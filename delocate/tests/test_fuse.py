"""Test fusing two directory trees / wheels."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from os.path import basename, dirname
from os.path import join as pjoin
from pathlib import Path

import pytest

from ..fuse import fuse_trees, fuse_wheels
from ..tmpdirs import InTemporaryDirectory
from ..tools import cmp_contents, dir2zip, get_archs, open_readable, zip2dir
from ..wheeltools import rewrite_record
from .pytest_tools import assert_equal, assert_false
from .test_tools import LIB64, LIB64A, LIBM1
from .test_wheelies import PURE_WHEEL
from .test_wheeltools import assert_record_equal


def assert_same_tree(
    tree1: str | Path, tree2: str | Path, *, updated_metadata: bool = False
) -> None:
    """Assert that `tree2` has files with the same content as `tree1`.

    If `updated_metadata` is True then the RECORD and WHEEL files are skipped.
    """
    for dirpath, dirnames, filenames in os.walk(tree1):
        tree2_dirpath = Path(tree2, Path(dirpath).relative_to(tree1))
        for dname in dirnames:
            assert Path(tree2_dirpath, dname).is_dir()
        for fname in filenames:
            tree1_path = Path(dirpath, fname)
            with open_readable(tree1_path, "rb") as fobj:
                contents1: bytes = fobj.read()
            with open_readable(Path(tree2_dirpath, fname), "rb") as fobj:
                contents2: bytes = fobj.read()
            if updated_metadata and fname in {"RECORD", "WHEEL"}:
                continue
            if fname == "RECORD":  # Record can have different line orders
                assert_record_equal(contents1, contents2)
            else:
                assert contents1 == contents2


def assert_listdir_equal(path, listing):
    assert sorted(os.listdir(path)) == sorted(listing)


@pytest.mark.xfail(sys.platform != "darwin", reason="lipo")
def test_fuse_trees():
    # Test function to fuse two paths
    with InTemporaryDirectory():
        os.mkdir("tree1")
        os.mkdir("tree2")
        fuse_trees("tree1", "tree2")
        assert_listdir_equal("tree1", [])
        with open(pjoin("tree2", "afile.txt"), "w") as fobj:
            fobj.write("Some text")
        fuse_trees("tree1", "tree2")
        assert_listdir_equal("tree1", ["afile.txt"])
        assert_same_tree("tree1", "tree2")
        # Copy this test directory, show it turns up in output
        shutil.copytree(dirname(__file__), pjoin("tree2", "tests"))
        fuse_trees("tree1", "tree2")
        assert_listdir_equal("tree1", ["afile.txt", "tests"])
        assert_same_tree("tree1", "tree2")
        # A library, not matched in to_tree
        shutil.copy2(LIB64A, "tree2")
        fuse_trees("tree1", "tree2")
        assert_listdir_equal("tree1", ["afile.txt", "liba.a", "tests"])
        assert_same_tree("tree1", "tree2")
        # Run the same again; this tests that there is no error when the
        # library is the same in both trees
        fuse_trees("tree1", "tree2")
        assert_same_tree("tree1", "tree2")
        # Real fuse
        shutil.copyfile(LIB64, pjoin("tree2", "tests", "liba.dylib"))
        shutil.copyfile(LIBM1, pjoin("tree1", "tests", "liba.dylib"))
        fuse_trees("tree1", "tree2")
        fused_fname = pjoin("tree1", "tests", "liba.dylib")
        assert_false(
            cmp_contents(fused_fname, pjoin("tree2", "tests", "liba.dylib"))
        )
        assert_equal(get_archs(fused_fname), {"arm64", "x86_64"})
        os.unlink(fused_fname)
        # A file not present in tree2 stays in tree1
        with open(pjoin("tree1", "anotherfile.txt"), "w") as fobj:
            fobj.write("Some more text")
        fuse_trees("tree1", "tree2")
        assert_listdir_equal(
            "tree1", ["afile.txt", "anotherfile.txt", "liba.a", "tests"]
        )


@pytest.mark.xfail(sys.platform != "darwin", reason="lipo")
def test_fuse_wheels() -> None:
    # Test function to fuse two wheels
    wheel_base = basename(PURE_WHEEL)
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "to_wheel")
        zip2dir(PURE_WHEEL, "from_wheel")
        dir2zip("to_wheel", "to_wheel.whl")
        dir2zip("from_wheel", "from_wheel.whl")
        fuse_wheels("to_wheel.whl", "from_wheel.whl", wheel_base)
        zip2dir(wheel_base, "fused_wheel")
        assert_same_tree("to_wheel", "fused_wheel")
        # Check unpacking works on fused wheel
        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", wheel_base], check=True
        )
        # Put lib into wheel
        shutil.copyfile(LIB64A, pjoin("from_wheel", "fakepkg2", "liba.a"))
        rewrite_record("from_wheel")
        dir2zip("from_wheel", "from_wheel.whl")
        fuse_wheels("to_wheel.whl", "from_wheel.whl", wheel_base)
        zip2dir(wheel_base, "fused_wheel")
        assert_same_tree("fused_wheel", "from_wheel")
        # Check we can fuse two identical wheels with a library in
        # (checks that fuse doesn't error for identical library)
        fuse_wheels(wheel_base, "from_wheel.whl", wheel_base)
        zip2dir(wheel_base, "fused_wheel")
        assert_same_tree("fused_wheel", "from_wheel")
        # Test fusing a library
        shutil.copyfile(LIB64, pjoin("from_wheel", "fakepkg2", "liba.dylib"))
        shutil.copyfile(LIBM1, pjoin("to_wheel", "fakepkg2", "liba.dylib"))
        dir2zip("from_wheel", "from_wheel.whl")
        dir2zip("to_wheel", "to_wheel.whl")
        fuse_wheels("to_wheel.whl", "from_wheel.whl", wheel_base)
        zip2dir(wheel_base, "fused_wheel")
        fused_fname = pjoin("fused_wheel", "fakepkg2", "liba.dylib")
        assert get_archs(fused_fname) == set(("arm64", "x86_64"))

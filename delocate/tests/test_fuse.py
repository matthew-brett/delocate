""" Test fusing two directory trees / wheels
"""

import os
from os.path import (join as pjoin, relpath, isdir, dirname, basename)
import shutil

from ..tools import cmp_contents, get_archs, zip2dir, dir2zip, back_tick
from ..fuse import fuse_trees, fuse_wheels
from ..tmpdirs import InTemporaryDirectory
from ..wheeltools import rewrite_record

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)


from .test_tools import LIB32, LIB64, LIB64A
from .test_wheelies import PURE_WHEEL


def assert_same_tree(tree1, tree2):
    for dirpath, dirnames, filenames in os.walk(tree1):
        tree2_dirpath = pjoin(tree2, relpath(dirpath, tree1))
        for dname in dirnames:
            assert_true(isdir(pjoin(tree2_dirpath, dname)))
        for fname in filenames:
            tree1_path = pjoin(dirpath, fname)
            assert_true(
                cmp_contents(tree1_path, pjoin(tree2_dirpath, fname)))


def test_fuse_trees():
    # Test function to fuse two paths
    with InTemporaryDirectory():
        os.mkdir('tree1')
        os.mkdir('tree2')
        fuse_trees('tree1', 'tree2')
        assert_equal(os.listdir('tree1'), [])
        with open(pjoin('tree2', 'afile.txt'), 'wt') as fobj:
            fobj.write('Some text')
        fuse_trees('tree1', 'tree2')
        assert_equal(os.listdir('tree1'), ['afile.txt'])
        assert_same_tree('tree1', 'tree2')
        # Copy this test directory, show it turns up in output
        shutil.copytree(dirname(__file__), pjoin('tree2', 'tests'))
        fuse_trees('tree1', 'tree2')
        assert_equal(os.listdir('tree1'), ['afile.txt', 'tests'])
        assert_same_tree('tree1', 'tree2')
        # A library, not matched in to_tree
        shutil.copy2(LIB64A, 'tree2')
        fuse_trees('tree1', 'tree2')
        assert_equal(os.listdir('tree1'), ['afile.txt', 'liba.a', 'tests'])
        assert_same_tree('tree1', 'tree2')
        # Run the same again; this tests that there is no error when the
        # library is the same in both trees
        fuse_trees('tree1', 'tree2')
        assert_same_tree('tree1', 'tree2')
        # Real fuse
        shutil.copyfile(LIB64, pjoin('tree2', 'tests', 'liba.dylib'))
        shutil.copyfile(LIB32, pjoin('tree1', 'tests', 'liba.dylib'))
        fuse_trees('tree1', 'tree2')
        fused_fname = pjoin('tree1', 'tests', 'liba.dylib')
        assert_false(cmp_contents(
            fused_fname,
            pjoin('tree2', 'tests', 'liba.dylib')))
        assert_equal(get_archs(fused_fname), set(('i386', 'x86_64')))
        os.unlink(fused_fname)
        # A file not present in tree2 stays in tree1
        with open(pjoin('tree1', 'anotherfile.txt'), 'wt') as fobj:
            fobj.write('Some more text')
        fuse_trees('tree1', 'tree2')
        assert_equal(os.listdir('tree1'),
                     ['afile.txt', 'anotherfile.txt', 'liba.a', 'tests'])



def test_fuse_wheels():
    # Test function to fuse two wheels
    wheel_base = basename(PURE_WHEEL)
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, 'to_wheel')
        zip2dir(PURE_WHEEL, 'from_wheel')
        dir2zip('to_wheel', 'to_wheel.whl')
        dir2zip('from_wheel', 'from_wheel.whl')
        fuse_wheels('to_wheel.whl', 'from_wheel.whl', wheel_base)
        zip2dir(wheel_base, 'fused_wheel')
        assert_same_tree('to_wheel', 'fused_wheel')
        # Check unpacking works on fused wheel
        back_tick(['wheel', 'unpack', wheel_base])
        # Put lib into wheel
        shutil.copyfile(LIB64A, pjoin('from_wheel', 'fakepkg2', 'liba.a'))
        rewrite_record('from_wheel')
        dir2zip('from_wheel', 'from_wheel.whl')
        fuse_wheels('to_wheel.whl', 'from_wheel.whl', wheel_base)
        zip2dir(wheel_base, 'fused_wheel')
        assert_same_tree('fused_wheel', 'from_wheel')
        # Check we can fuse two identical wheels with a library in
        # (checks that fuse doesn't error for identical library)
        fuse_wheels(wheel_base, 'from_wheel.whl', wheel_base)
        zip2dir(wheel_base, 'fused_wheel')
        assert_same_tree('fused_wheel', 'from_wheel')
        # Test fusing a library
        shutil.copyfile(LIB64, pjoin('from_wheel', 'fakepkg2', 'liba.dylib'))
        shutil.copyfile(LIB32, pjoin('to_wheel', 'fakepkg2', 'liba.dylib'))
        dir2zip('from_wheel', 'from_wheel.whl')
        dir2zip('to_wheel', 'to_wheel.whl')
        fuse_wheels('to_wheel.whl', 'from_wheel.whl', wheel_base)
        zip2dir(wheel_base, 'fused_wheel')
        fused_fname = pjoin('fused_wheel', 'fakepkg2', 'liba.dylib')
        assert_equal(get_archs(fused_fname), set(('i386', 'x86_64')))

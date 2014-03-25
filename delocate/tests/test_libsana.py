""" Tests for libsana module

Utilities for analyzing library dependencies in trees and wheels
"""

from os.path import join as pjoin, split as psplit, abspath, dirname

from ..libsana import tree_libs, wheel_libs
from ..tools import set_install_name

from ..tmpdirs import InTemporaryDirectory

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import (LIBA, LIBB, LIBC, TEST_LIB, _copy_libs)
from .test_wheelies import PLAT_WHEEL, PURE_WHEEL, STRAY_LIB_DEP

def test_tree_libs():
    # Test ability to walk through tree, finding dynamic libary refs
    # Copy specific files to avoid working tree cruft
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        liba, libb, libc, test_lib = _copy_libs(to_copy, tmpdir)
        assert_equal(
            tree_libs(tmpdir), # default - no filtering
            {'/usr/lib/libstdc++.6.dylib': set([liba, libb, libc, test_lib]),
             '/usr/lib/libSystem.B.dylib': set([liba, libb, libc, test_lib]),
             'liba.dylib': set([libb, libc]),
             'libb.dylib': set([libc]),
             'libc.dylib': set([test_lib])})
        def filt(fname):
            return fname.endswith('.dylib')
        assert_equal(
            tree_libs(tmpdir, filt), # filtering
            {'/usr/lib/libstdc++.6.dylib': set([liba, libb, libc]),
             '/usr/lib/libSystem.B.dylib': set([liba, libb, libc]),
             'liba.dylib': set([libb, libc]),
             'libb.dylib': set([libc])})
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, 'subtree')
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        assert_equal(
            tree_libs(tmpdir, filt), # filtering
            {'/usr/lib/libstdc++.6.dylib':
             set([liba, libb, libc, slibc]),
             '/usr/lib/libSystem.B.dylib':
             set([liba, libb, libc, slibc]),
             'liba.dylib': set([libb, libc, slibc]),
             'libb.dylib': set([libc, slibc])})
        set_install_name(slibc, 'liba.dylib', 'newlib')
        assert_equal(
            tree_libs(tmpdir, filt), # filtering
            {'/usr/lib/libstdc++.6.dylib':
             set([liba, libb, libc, slibc]),
             '/usr/lib/libSystem.B.dylib':
             set([liba, libb, libc, slibc]),
             'liba.dylib': set([libb, libc]),
             'newlib': set([slibc]),
             'libb.dylib': set([libc, slibc])})


def test_wheel_libs():
    # Test routine to list dependencies from wheels
    assert_equal(wheel_libs(PURE_WHEEL), {})
    mod2 = pjoin('.', 'fakepkg1', 'subpkg', 'module2.so')
    assert_equal(wheel_libs(PLAT_WHEEL),
                 {STRAY_LIB_DEP: set([mod2]),
                  '/usr/lib/libSystem.B.dylib': set([mod2])})
    def filt(fname):
        return not fname == mod2
    assert_equal(wheel_libs(PLAT_WHEEL, filt), {})

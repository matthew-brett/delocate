""" Tests for relocating libraries """

from __future__ import division, print_function

import os
from os.path import (join as pjoin, split as psplit, abspath, dirname, basename,
                     exists)

from ..delocator import delocate_tree_libs, get_install_names, get_rpath
from ..tools import tree_libs, set_install_name

from ..tmpdirs import InTemporaryDirectory

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import (DATA_PATH, LIBA, LIBB, LIBC, TEST_LIB,
                                 _copy_libs)


def test_delocate_tree_libs():
    # Test routine to copy library dependencies into a local directory
    with InTemporaryDirectory() as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, 'subtree')
        liba, libb, libc, test_lib = _copy_libs(
            [LIBA, LIBB, LIBC, TEST_LIB], subtree)
        subsubtree = pjoin(subtree, 'further')
        slibb, slibc, stest_lib = _copy_libs([libb, libc, test_lib], subsubtree)
        lib_dict = tree_libs(subtree)
        # By default we'll fail to find liba etc because of the relative paths
        assert_raises(delocate_tree_libs, lib_dict, 'dynlibs')
        # Fixup the library names by setting absolute paths
        for key, replacement in (('liba.dylib', liba),
                                 ('libb.dylib', libb),
                                 ('libc.dylib', libc)):
            for using_lib in lib_dict[key]:
                set_install_name(using_lib, key, replacement)
        delocate_tree_libs(lib_dict, 'dynlibs')
        assert_equal(sorted(os.listdir('dynlibs')),
                     ['libSystem.B.dylib', 'liba.dylib', 'libb.dylib',
                      'libc.dylib', 'libstdc++.6.dylib'])
        for lib in (liba, libc, libc, test_lib):
            assert_equal(get_rpath(lib), ('../dynlibs',))
        for lib in (slibb, slibc, stest_lib):
            assert_equal(get_rpath(lib), ('../../dynlibs',))
        new_libb = pjoin(tmpdir, 'dynlibs', 'libb.dylib')
        assert_equal(set(get_install_names(new_libb)),
                     set(('@rpath/liba.dylib',
                          '@rpath/libstdc++.6.dylib',
                          '@rpath/libSystem.B.dylib')))

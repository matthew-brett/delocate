""" Tests for relocating libraries """

from __future__ import division, print_function

import os
from os.path import (join as pjoin, split as psplit, abspath, dirname, basename,
                     exists)

from subprocess import Popen, PIPE, check_call

from ..delocator import delocate_tree_libs
from ..tools import (tree_libs, get_install_names, get_rpaths,
                     set_install_name, back_tick)

from ..tmpdirs import InTemporaryDirectory

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import (DATA_PATH, LIBA, LIBB, LIBC, TEST_LIB,
                                 _copy_libs)


def _make_libtree(out_path):
    liba, libb, libc, test_lib = _copy_libs(
        [LIBA, LIBB, LIBC, TEST_LIB], out_path)
    sub_path = pjoin(out_path, 'subsub')
    slibc, stest_lib = _copy_libs([libc, test_lib], sub_path)
    # Check test-lib doesn't work because of relative library paths
    assert_raises(RuntimeError, back_tick, [test_lib])
    assert_raises(RuntimeError, back_tick, [stest_lib])
    # Fixup the relative path library names by setting absolute paths
    for fname, using, path in (
        (libb, 'liba.dylib', out_path),
        (libc, 'liba.dylib', out_path),
        (libc, 'libb.dylib', out_path),
        (test_lib, 'libc.dylib', out_path),
        (slibc, 'liba.dylib', out_path),
        (slibc, 'libb.dylib', out_path),
        (stest_lib, 'libc.dylib', sub_path),
                        ):
        set_install_name(fname, using, pjoin(path, using))
    # Check test_lib works
    back_tick([test_lib])
    back_tick([stest_lib])
    return liba, libb, libc, test_lib, slibc, stest_lib


def test_delocate_tree_libs():
    # Test routine to copy library dependencies into a local directory
    with InTemporaryDirectory() as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, 'subtree')
        liba, libb, libc, test_lib, slibc, stest_lib = _make_libtree(subtree)
        lib_dict = tree_libs(subtree)
        # By default we'll fail to find liba etc because of the relative paths
        assert_raises(ValueError, delocate_tree_libs, lib_dict, 'dynlibs')
        # Fixup the library names by setting absolute paths
        for key, replacement in (('liba.dylib', liba),
                                 ('libb.dylib', libb),
                                 ('libc.dylib', libc)):
            for using_lib in lib_dict[key]:
                set_install_name(using_lib, key, replacement)
        delocate_tree_libs(lib_dict, 'dynlibs')
        # All the libraries linked to get copied
        assert_equal(sorted(os.listdir('dynlibs')),
                     ['libSystem.B.dylib', 'liba.dylib', 'libb.dylib',
                      'libc.dylib', 'libstdc++.6.dylib'])
        # All linking libraries now have a relative rpath and a link to the
        # copied library via the rpath
        for required, requirings in lib_dict.items():
            rpathed = '@rpath/' + basename(required)
            for requiring in requirings:
                assert_equal(get_rpaths(requiring),
                             ('@loader_path/../dynlibs',))
                assert_true(rpathed in get_install_names(requiring))
        # The copied library also links to local libraries via relative path
        # Could be also be just @loader_path in the install names of course.
        new_libb = pjoin(tmpdir, 'dynlibs', 'libb.dylib')
        assert_equal(set(get_install_names(new_libb)),
                     set(('@rpath/liba.dylib',
                          '@rpath/libstdc++.6.dylib',
                          '@rpath/libSystem.B.dylib')))
        assert_equal(get_rpaths(new_libb), ('@loader_path',))
    # Do the same, but with the option to keep libraries in the tree
    with InTemporaryDirectory() as tmpdir:
        subtree = pjoin(tmpdir, 'subtree')
        liba, libb, libc, test_lib = _copy_libs(
            [LIBA, LIBB, LIBC, TEST_LIB], subtree)
        subsubtree = pjoin(subtree, 'further')
        slibb, slibc, stest_lib = _copy_libs([libb, libc, test_lib], subsubtree)
        lib_dict = tree_libs(subtree)
        # Fixup the library names by setting absolute paths
        for key, replacement in (('liba.dylib', liba),
                                 ('libb.dylib', libb),
                                 ('libc.dylib', libc)):
            for using_lib in lib_dict[key]:
                set_install_name(using_lib, key, replacement)
        # Now do copy preserving in-tree libraries
        delocate_tree_libs(lib_dict, 'dynlibs', 'subtree')
        # Only the out-of-tree libraries get copied
        ext_libs = ['libSystem.B.dylib', 'libstdc++.6.dylib']
        assert_equal(sorted(os.listdir('dynlibs')), ext_libs)
        for key in ext_libs:
            for requiring in lib_dict[key]:
                assert_equal(get_rpaths(requiring),
                             ('@loader_path/../dynlibs',))
                assert_true(rpathed in get_install_names(requiring))


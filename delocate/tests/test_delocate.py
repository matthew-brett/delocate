""" Tests for relocating libraries """

from __future__ import division, print_function

import os
from os.path import (join as pjoin, dirname, basename, relpath)

from ..delocator import delocate_tree_libs, DelocationError
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
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        lib_dict = tree_libs(subtree)
        copy_dir = 'dynlibs'
        os.makedirs(copy_dir)
        copied = delocate_tree_libs(lib_dict, copy_dir, subtree)
        # Only the out-of-tree libraries get copied
        ext_libs = set(('/usr/lib/libstdc++.6.dylib',
                        '/usr/lib/libSystem.B.dylib'))
        assert_equal(copied, ext_libs)
        assert_equal(set(os.listdir(copy_dir)),
                     set([basename(lib) for lib in ext_libs]))
        # Libraries using the copied libraries now have an rpath pointing to
        # the copied library directory, and rpath/libname as install names
        to_exts = set(['@rpath/' + basename(elib) for elib in copied])
        for lib in all_local_libs:
            pathto_copies = relpath(copy_dir, dirname(lib))
            assert_equal(get_rpaths(lib), ('@loader_path/' + pathto_copies,))
            assert_true(to_exts <= set(get_install_names(lib)))
        # Libraries now have a relative loader_path to their corresponding
        # in-tree libraries
        for requiring, using, rel_path in (
            (libb, 'liba.dylib', ''),
            (libc, 'liba.dylib', ''),
            (libc, 'libb.dylib', ''),
            (test_lib, 'libc.dylib', ''),
            (slibc, 'liba.dylib', '../'),
            (slibc, 'libb.dylib', '../'),
            (stest_lib, 'libc.dylib', '')):
            loader_path = '@loader_path/' + rel_path + using
            assert_true(loader_path in get_install_names(requiring))
        # Check test libs still work
        back_tick([test_lib])
        back_tick([stest_lib])
        # Check case where all local libraries are out of tree
        subtree2 = pjoin(tmpdir, 'subtree2')
        liba, libb, libc, test_lib, slibc, stest_lib = _make_libtree(subtree2)
        copy_dir2 = 'dynlibs2'
        os.makedirs(copy_dir2)
        # Trying to delocate where all local libraries appear to be
        # out-of-tree will raise an error because of duplicate library names
        lib_dict2 = tree_libs(subtree2)
        assert_raises(DelocationError,
                      delocate_tree_libs, lib_dict2, copy_dir2, '/tmp')
        # Rename a library to make this work
        new_slibc = pjoin(dirname(slibc), 'libc2.dylib')
        os.rename(slibc, new_slibc)
        # Tell test-lib about this
        set_install_name(stest_lib, slibc, new_slibc)
        slibc = new_slibc
        # Confirm new test-lib still works
        back_tick([stest_lib])
        # Delocation now works
        lib_dict2 = tree_libs(subtree2)
        copied2 = delocate_tree_libs(lib_dict2, copy_dir2, '/tmp')
        ext_local_libs = ext_libs | set([liba, libb, libc, slibc])
        assert_equal(copied2, ext_local_libs)
        assert_equal(set(os.listdir(copy_dir2)),
                     set([basename(lib) for lib in ext_local_libs]))
        # Libraries using the copied libraries now have an rpath pointing to
        # the copied library directory, and rpath/libname as install names
        all_local_libs = liba, libb, libc, test_lib, slibc, stest_lib
        for lib in all_local_libs:
            pathto_copies = relpath(copy_dir2, dirname(lib))
            assert_equal(get_rpaths(lib), ('@loader_path/' + pathto_copies,))
            assert_true(to_exts <= set(get_install_names(lib)))

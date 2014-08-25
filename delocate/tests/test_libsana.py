""" Tests for libsana module

Utilities for analyzing library dependencies in trees and wheels
"""

import os
from os.path import (join as pjoin, dirname, realpath, relpath)

from ..libsana import (tree_libs, get_prefix_stripper, get_rp_stripper,
                       stripped_lib_dict, wheel_libs)

from ..tools import set_install_name

from ..tmpdirs import InTemporaryDirectory

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import (LIBA, LIBB, LIBC, TEST_LIB, _copy_libs,
                                 EXT_LIBS, LIBSYSTEMB)
from .test_wheelies import (PLAT_WHEEL, PURE_WHEEL, STRAY_LIB_DEP)


def get_ext_dict(local_libs):
    ext_deps = {}
    for ext_lib in EXT_LIBS:
        lib_deps = {}
        for local_lib in local_libs:
            lib_deps[realpath(local_lib)] = ext_lib
        ext_deps[realpath(ext_lib)] = lib_deps
    return ext_deps


def test_tree_libs():
    # Test ability to walk through tree, finding dynamic libary refs
    # Copy specific files to avoid working tree cruft
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        rp_local_libs = [realpath(L) for L in local_libs]
        liba, libb, libc, test_lib = local_libs
        rp_liba, rp_libb, rp_libc, rp_test_lib = rp_local_libs
        exp_dict = get_ext_dict(local_libs)
        exp_dict.update({
             rp_liba: {rp_libb: 'liba.dylib', rp_libc: 'liba.dylib'},
             rp_libb: {rp_libc: 'libb.dylib'},
             rp_libc: {rp_test_lib: 'libc.dylib'}})
        # default - no filtering
        assert_equal(tree_libs(tmpdir), exp_dict)
        def filt(fname):
            return fname.endswith('.dylib')
        exp_dict = get_ext_dict([liba, libb, libc])
        exp_dict.update({
             rp_liba: {rp_libb: 'liba.dylib', rp_libc: 'liba.dylib'},
             rp_libb: {rp_libc: 'libb.dylib'}})
        # filtering
        assert_equal(tree_libs(tmpdir, filt), exp_dict)
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, 'subtree')
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        st_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        st_exp_dict.update({
            rp_liba: {rp_libb: 'liba.dylib',
                      rp_libc: 'liba.dylib',
                      realpath(slibc): 'liba.dylib'},
            rp_libb: {rp_libc: 'libb.dylib',
                      realpath(slibc): 'libb.dylib'}})
        assert_equal(tree_libs(tmpdir, filt), st_exp_dict)
        # Change an install name, check this is picked up
        set_install_name(slibc, 'liba.dylib', 'newlib')
        inc_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        inc_exp_dict.update({
            rp_liba: {rp_libb: 'liba.dylib',
                      rp_libc: 'liba.dylib'},
            realpath('newlib'): {realpath(slibc): 'newlib'},
            rp_libb: {rp_libc: 'libb.dylib',
                      realpath(slibc): 'libb.dylib'}})
        assert_equal(tree_libs(tmpdir, filt), inc_exp_dict)
        # Symlink a depending canonical lib - should have no effect because of
        # the canonical names
        os.symlink(liba, pjoin(dirname(liba), 'funny.dylib'))
        assert_equal(tree_libs(tmpdir, filt), inc_exp_dict)
        # Symlink a depended lib.  Now 'newlib' is a symlink to liba, and the
        # dependency of slibc on newlib appears as a dependency on liba, but
        # with install name 'newlib'
        os.symlink(liba, 'newlib')
        sl_exp_dict = get_ext_dict([liba, libb, libc, slibc])
        sl_exp_dict.update({
            rp_liba: {rp_libb: 'liba.dylib',
                      rp_libc: 'liba.dylib',
                      realpath(slibc): 'newlib'},
            rp_libb: {rp_libc: 'libb.dylib',
                      realpath(slibc): 'libb.dylib'}})
        assert_equal(tree_libs(tmpdir, filt), sl_exp_dict)


def test_get_prefix_stripper():
    # Test function factory to strip prefixes
    f = get_prefix_stripper('')
    assert_equal(f('a string'), 'a string')
    f = get_prefix_stripper('a ')
    assert_equal(f('a string'), 'string')
    assert_equal(f('b string'), 'b string')
    assert_equal(f('b a string'), 'b a string')


def test_get_rp_stripper():
    # realpath prefix stripper
    # Just does realpath and adds path sep
    cwd = realpath(os.getcwd())
    f = get_rp_stripper('') # pwd
    test_path = pjoin('test', 'path')
    assert_equal(f(test_path), test_path)
    rp_test_path = pjoin(cwd, test_path)
    assert_equal(f(rp_test_path), test_path)
    f = get_rp_stripper(pjoin(cwd, 'test'))
    assert_equal(f(rp_test_path), 'path')


def get_ext_dict_stripped(local_libs, start_path):
    ext_dict = {}
    for ext_lib in EXT_LIBS:
        lib_deps = {}
        for local_lib in local_libs:
            dep_path = relpath(local_lib, start_path)
            if dep_path.startswith('./'):
                dep_path = dep_path[2:]
            lib_deps[dep_path] = ext_lib
        ext_dict[realpath(ext_lib)] = lib_deps
    return ext_dict


def test_stripped_lib_dict():
    # Test routine to return lib_dict with relative paths
    to_copy = [LIBA, LIBB, LIBC, TEST_LIB]
    with InTemporaryDirectory() as tmpdir:
        local_libs = _copy_libs(to_copy, tmpdir)
        exp_dict = get_ext_dict_stripped(local_libs, tmpdir)
        exp_dict.update({
            'liba.dylib': {'libb.dylib': 'liba.dylib',
                           'libc.dylib': 'liba.dylib'},
            'libb.dylib': {'libc.dylib': 'libb.dylib'},
            'libc.dylib': {'test-lib': 'libc.dylib'}})
        my_path = realpath(tmpdir) + os.path.sep
        assert_equal(stripped_lib_dict(tree_libs(tmpdir), my_path), exp_dict)
        # Copy some libraries into subtree to test tree walking
        subtree = pjoin(tmpdir, 'subtree')
        liba, libb, libc, test_lib = local_libs
        slibc, stest_lib = _copy_libs([libc, test_lib], subtree)
        exp_dict = get_ext_dict_stripped(local_libs + [slibc, stest_lib],
                                         tmpdir)
        exp_dict.update({
            'liba.dylib': {'libb.dylib': 'liba.dylib',
                           'libc.dylib': 'liba.dylib',
                           'subtree/libc.dylib': 'liba.dylib',
                          },
            'libb.dylib': {'libc.dylib': 'libb.dylib',
                           'subtree/libc.dylib': 'libb.dylib',
                          },
            'libc.dylib': {'test-lib': 'libc.dylib',
                           'subtree/test-lib': 'libc.dylib',
                          }})
        assert_equal(stripped_lib_dict(tree_libs(tmpdir), my_path), exp_dict)


def test_wheel_libs():
    # Test routine to list dependencies from wheels
    assert_equal(wheel_libs(PURE_WHEEL), {})
    mod2 = pjoin('fakepkg1', 'subpkg', 'module2.so')
    assert_equal(wheel_libs(PLAT_WHEEL),
                 {STRAY_LIB_DEP: {mod2: STRAY_LIB_DEP},
                  realpath(LIBSYSTEMB): {mod2: LIBSYSTEMB}})
    def filt(fname):
        return not fname.endswith(mod2)
    assert_equal(wheel_libs(PLAT_WHEEL, filt), {})

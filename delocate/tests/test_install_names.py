""" Tests for otool utility """

from os.path import join as pjoin, split as psplit, abspath, dirname

from ..tools import get_install_names, get_install_id

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)


DATA_PATH = pjoin(dirname(__file__), 'data')
LIBA = pjoin(DATA_PATH, 'liba.dylib')
LIBB = pjoin(DATA_PATH, 'libb.dylib')
LIBC = pjoin(DATA_PATH, 'libc.dylib')
TEST_LIB = pjoin(DATA_PATH, 'test-lib')

def test_install_names():
    # Test basic otool listing
    assert_equal(get_install_names(LIBA),
                 ['/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])
    assert_equal(get_install_names(LIBB),
                 ['liba.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])
    assert_equal(get_install_names(TEST_LIB),
                 ['libc.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])


def test_install_id():
    # Test basic otool library listing
    assert_equal(get_install_id(LIBA),
                 ['/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])
    assert_equal(get_install_names(LIBB),
                 ['liba.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])
    assert_equal(get_install_names(TEST_LIB),
                 ['libc.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'])

""" Tests for otool utility """

from os.path import join as pjoin, split as psplit, abspath, dirname

import shutil

from ..tools import (get_install_names, set_install_name, get_install_id,
                     get_rpaths, add_rpath, parse_install_name,
                     set_install_id)

from ..tmpdirs import InTemporaryDirectory

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
                 ('/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'))
    assert_equal(get_install_names(LIBB),
                 ('liba.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'))
    assert_equal(get_install_names(TEST_LIB),
                 ('libc.dylib',
                  '/usr/lib/libc++.1.dylib',
                  '/usr/lib/libSystem.B.dylib'))


def test_parse_install_name():
    assert_equal(parse_install_name(
        "liba.dylib (compatibility version 0.0.0, current version 0.0.0)"),
        ("liba.dylib", "0.0.0", "0.0.0"))
    assert_equal(parse_install_name(
        " /usr/lib/libc++.1.dylib (compatibility version 1.0.0, "
        "current version 120.0.0)"),
        ("/usr/lib/libc++.1.dylib", "1.0.0", "120.0.0"))
    assert_equal(parse_install_name(
        "\t\t   /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, "
        "current version 1197.1.1)"),
        ("/usr/lib/libSystem.B.dylib", "1.0.0", "1197.1.1"))


def test_install_id():
    # Test basic otool library listing
    assert_equal(get_install_id(LIBA), 'liba.dylib')
    assert_equal(get_install_id(LIBB), 'libb.dylib')
    assert_equal(get_install_id(LIBC), 'libc.dylib')
    assert_equal(get_install_id(TEST_LIB), None)


def test_change_install_name():
    # Test ability to change install names in library
    libb_names = get_install_names(LIBB)
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, 'libfoo.dylib')
        shutil.copy2(LIBB, libfoo)
        assert_equal(get_install_names(libfoo), libb_names)
        set_install_name(libfoo, 'liba.dylib', 'libbar.dylib')
        assert_equal(get_install_names(libfoo),
                     ('libbar.dylib',) + libb_names[1:])
        # If the name not found, raise an error
        assert_raises(RuntimeError,
                      set_install_name, libfoo, 'liba.dylib', 'libpho.dylib')


def test_set_install_id():
    # Test ability to change install id in library
    liba_id = get_install_id(LIBA)
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, 'libfoo.dylib')
        shutil.copy2(LIBA, libfoo)
        assert_equal(get_install_id(libfoo), liba_id)
        set_install_id(libfoo, 'libbar.dylib')
        assert_equal(get_install_id(libfoo), 'libbar.dylib')
    # If no install id, raise error (unlike install_name_tool)
    assert_raises(RuntimeError, set_install_id, TEST_LIB, 'libbof.dylib')


def test_add_rpath():
    # Test adding to rpath
    assert_equal(get_rpaths(LIBB), ())
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, 'libfoo.dylib')
        shutil.copy2(LIBB, libfoo)
        assert_equal(get_rpaths(libfoo), ())
        add_rpath(libfoo, '/a/path')
        assert_equal(get_rpaths(libfoo), ('/a/path',))
        add_rpath(libfoo, '/another/path')
        assert_equal(get_rpaths(libfoo), ('/a/path', '/another/path'))

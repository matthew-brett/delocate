""" Tests for install name utilities """

import os
from os.path import (join as pjoin, exists, dirname, basename)

import shutil

from ..tools import (InstallNameError, get_install_names, set_install_name,
                     get_install_id, get_rpaths, add_rpath, parse_install_name,
                     set_install_id, get_environment_variable_paths)

from ..tmpdirs import InTemporaryDirectory

from .pytest_tools import (assert_raises, assert_equal)
from .env_tools import TempDirWithoutEnvVars

# External libs linked from test data
LIBSTDCXX = '/usr/lib/libstdc++.6.dylib'
LIBSYSTEMB = '/usr/lib/libSystem.B.dylib'
EXT_LIBS = (LIBSTDCXX, LIBSYSTEMB)

DATA_PATH = pjoin(dirname(__file__), 'data')
LIBA = pjoin(DATA_PATH, 'liba.dylib')
LIBB = pjoin(DATA_PATH, 'libb.dylib')
LIBC = pjoin(DATA_PATH, 'libc.dylib')
LIBA_STATIC = pjoin(DATA_PATH, 'liba.a')
A_OBJECT = pjoin(DATA_PATH, 'a.o')
TEST_LIB = pjoin(DATA_PATH, 'test-lib')
ICO_FILE = pjoin(DATA_PATH, 'icon.ico')
PY_FILE = pjoin(DATA_PATH, 'some_code.py')
BIN_FILE = pjoin(DATA_PATH, 'binary_example.bin')


def test_get_install_names():
    # Test install name listing
    assert_equal(set(get_install_names(LIBA)),
                 set(EXT_LIBS))
    assert_equal(set(get_install_names(LIBB)),
                 set(('liba.dylib',) + EXT_LIBS))
    assert_equal(set(get_install_names(LIBC)),
                 set(('liba.dylib', 'libb.dylib') + EXT_LIBS))
    assert_equal(set(get_install_names(TEST_LIB)),
                 set(('libc.dylib',) + EXT_LIBS))
    # Non-object file returns empty tuple
    assert_equal(get_install_names(__file__), ())
    # Static archive and object files returns empty tuple
    assert_equal(get_install_names(A_OBJECT), ())
    assert_equal(get_install_names(LIBA_STATIC), ())
    # ico file triggers another error message and should also return an empty tuple  # noqa: E501
    assert_equal(get_install_names(ICO_FILE), ())
    # Python file (__file__ above may be a pyc file)
    assert_equal(get_install_names(PY_FILE), ())
    # Binary file (in fact a truncated SAS file)
    assert_equal(get_install_names(BIN_FILE), ())
    # Test when no read permission
    with InTemporaryDirectory():
        shutil.copyfile(LIBA, 'test.dylib')
        assert_equal(set(get_install_names('test.dylib')),
                     set(EXT_LIBS))
        # No permissions, no found libs
        os.chmod('test.dylib', 0)
        assert_equal(get_install_names('test.dylib'), ())


def test_parse_install_name():
    assert_equal(parse_install_name(
        "liba.dylib (compatibility version 0.0.0, current version 0.0.0)"),
        ("liba.dylib", "0.0.0", "0.0.0"))
    assert_equal(parse_install_name(
        " /usr/lib/libstdc++.6.dylib (compatibility version 1.0.0, "
        "current version 120.0.0)"),
        ("/usr/lib/libstdc++.6.dylib", "1.0.0", "120.0.0"))
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
    # Non-object file returns None too
    assert_equal(get_install_id(__file__), None)
    assert_equal(get_install_id(ICO_FILE), None)


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
        assert_raises(InstallNameError,
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
    assert_raises(InstallNameError, set_install_id, TEST_LIB, 'libbof.dylib')


def test_get_rpaths():
    # Test fetch of rpaths
    # Not dynamic libs, no rpaths
    for fname in (LIBB, A_OBJECT, LIBA_STATIC, ICO_FILE, PY_FILE, BIN_FILE):
        assert_equal(get_rpaths(fname), ())


def test_get_environment_variable_paths():
    # Test that environment variable paths are fetched in a specific order
    with TempDirWithoutEnvVars('DYLD_FALLBACK_LIBRARY_PATH',
                               'DYLD_LIBRARY_PATH'):
        os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = 'three'
        os.environ['DYLD_LIBRARY_PATH'] = 'two'
        assert_equal(get_environment_variable_paths(), ('two', 'three'))


def test_add_rpath():
    # Test adding to rpath
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, 'libfoo.dylib')
        shutil.copy2(LIBB, libfoo)
        assert_equal(get_rpaths(libfoo), ())
        add_rpath(libfoo, '/a/path')
        assert_equal(get_rpaths(libfoo), ('/a/path',))
        add_rpath(libfoo, '/another/path')
        assert_equal(get_rpaths(libfoo), ('/a/path', '/another/path'))
        add_rpath(libfoo, '@loader_path')
        assert_equal(get_rpaths(libfoo), ('/a/path', '/another/path', tmpdir))


def _copy_libs(lib_files, out_path):
    copied = []
    if not exists(out_path):
        os.makedirs(out_path)
    for in_fname in lib_files:
        out_fname = pjoin(out_path, basename(in_fname))
        shutil.copy2(in_fname, out_fname)
        copied.append(out_fname)
    return copied

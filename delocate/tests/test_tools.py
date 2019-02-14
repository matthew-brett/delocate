""" Test tools module """
from __future__ import division, print_function

from os.path import join as pjoin, dirname
import shutil

from ..tools import (back_tick, get_archs, lipo_fuse, replace_signature,
                     validate_signature, add_rpath)
from ..tmpdirs import InTemporaryDirectory

from .pytest_tools import assert_equal, assert_raises

DATA_PATH = pjoin(dirname(__file__), 'data')
LIB32 = pjoin(DATA_PATH, 'liba32.dylib')
LIB64 = pjoin(DATA_PATH, 'liba.dylib')
LIBBOTH = pjoin(DATA_PATH, 'liba_both.dylib')
LIB64A = pjoin(DATA_PATH, 'liba.a')
ARCH_64 = frozenset(['x86_64'])
ARCH_32 = frozenset(['i386'])
ARCH_BOTH = ARCH_64 | ARCH_32


def test_get_archs_fuse():
    # Test routine to get architecture types from file
    assert_equal(get_archs(LIB32), ARCH_32)
    assert_equal(get_archs(LIB64), ARCH_64)
    assert_equal(get_archs(LIB64A), ARCH_64)
    assert_equal(get_archs(LIBBOTH), ARCH_BOTH)
    assert_raises(RuntimeError, get_archs, 'not_a_file')
    with InTemporaryDirectory():
        lipo_fuse(LIB32, LIB64, 'anotherlib')
        assert_equal(get_archs('anotherlib'), ARCH_BOTH)
        lipo_fuse(LIB64, LIB32, 'anotherlib')
        assert_equal(get_archs('anotherlib'), ARCH_BOTH)
        shutil.copyfile(LIB32, 'libcopy32')
        lipo_fuse('libcopy32', LIB64, 'anotherlib')
        assert_equal(get_archs('anotherlib'), ARCH_BOTH)
        assert_raises(RuntimeError, lipo_fuse, 'libcopy32', LIB32, 'yetanother')
        shutil.copyfile(LIB64, 'libcopy64')
        assert_raises(RuntimeError, lipo_fuse, 'libcopy64', LIB64, 'yetanother')


def test_validate_signature():
    # Fully test the validate_signature tool
    def check_signature(filename):
        """Raises RuntimeError if codesign can not verify the signature."""
        back_tick(['codesign', '--verify', filename], raise_err=True)

    with InTemporaryDirectory():
        # Copy a binary file to test with, any binary file would work
        shutil.copyfile(LIBBOTH, 'libcopy')

        # validate_signature does not add missing signatures
        validate_signature('libcopy')

        # codesign should raise an error (missing signature)
        assert_raises(RuntimeError, check_signature, 'libcopy')

        replace_signature('libcopy', '-') # Force this file to be signed
        validate_signature('libcopy') # Cover the `is already valid` code path

        check_signature('libcopy') # codesign now accepts the file

        # Alter the contents of this file, this will invalidate the signature
        add_rpath('libcopy', '/dummy/path')

        # codesign should raise a new error (invalid signature)
        assert_raises(RuntimeError, check_signature, 'libcopy')

        validate_signature('libcopy') # Replace the broken signature
        check_signature('libcopy')

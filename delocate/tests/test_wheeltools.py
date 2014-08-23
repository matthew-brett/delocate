""" Tests for wheeltools utilities
"""

import os
from os.path import join as pjoin, exists, isfile, basename, realpath
import shutil

from ..wheeltools import rewrite_record, InWheel, WheelToolsError
from ..tmpdirs import InTemporaryDirectory
from ..tools import zip2dir

from nose.tools import (assert_true, assert_false, assert_raises, assert_equal)

from .test_wheelies import PURE_WHEEL


def test_rewrite_record():
    dist_info_sdir = 'fakepkg2-1.0.dist-info'
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, 'wheel')
        record_fname = pjoin('wheel', dist_info_sdir, 'RECORD')
        with open(record_fname, 'rt') as fobj:
            record_orig = fobj.read()
        # Test we get the same record by rewriting
        os.unlink(record_fname)
        rewrite_record('wheel')
        with open(record_fname, 'rt') as fobj:
            record_new = fobj.read()
        assert_equal(record_orig, record_new)
        # Test that signature gets deleted
        sig_fname = pjoin('wheel', dist_info_sdir, 'RECORD.jws')
        with open(sig_fname, 'wt') as fobj:
            fobj.write('something')
        rewrite_record('wheel')
        with open(record_fname, 'rt') as fobj:
            record_new = fobj.read()
        assert_equal(record_orig, record_new)
        assert_false(exists(sig_fname))
        # Test error for too many dist-infos
        shutil.copytree(pjoin('wheel', dist_info_sdir),
                        pjoin('wheel', 'anotherpkg-2.0.dist-info'))
        assert_raises(WheelToolsError, rewrite_record, 'wheel')


def test_in_wheel():
    # Test in-wheel decorator
    with InWheel(PURE_WHEEL) as wheel_path: # No output wheel
        shutil.rmtree('fakepkg2')
        res = sorted(os.listdir('.'))
        assert_equal(realpath(wheel_path), realpath(os.getcwd()))
    assert_equal(res, ['fakepkg2-1.0.dist-info'])
    # The original wheel unchanged
    with InWheel(PURE_WHEEL, ret_self=True) as ctx: # No output wheel
        res = sorted(os.listdir('.'))
        assert_equal(realpath(ctx.wheel_path), realpath(os.getcwd()))
    assert_equal(res, ['fakepkg2', 'fakepkg2-1.0.dist-info'])
    # Make an output wheel file in a temporary directory
    with InTemporaryDirectory():
        mod_path = pjoin('fakepkg2', 'module1.py')
        with InWheel(PURE_WHEEL, 'mungled.whl'):
            assert_true(isfile(mod_path))
            os.unlink(mod_path)
        with InWheel('mungled.whl'):
            assert_false(isfile(mod_path))
    # Do the same, but set wheel name post-hoc
    with InTemporaryDirectory() as tmpdir:
        mod_path = pjoin('fakepkg2', 'module1.py')
        with InWheel(PURE_WHEEL, ret_self=True) as ctx:
            assert_true(isfile(mod_path))
            os.unlink(mod_path)
            # Set output name in context manager, so write on output
            ctx.out_wheel = pjoin(tmpdir, 'mungled.whl')
        with InWheel('mungled.whl'):
            assert_false(isfile(mod_path))

""" Tests for wheeltools utilities
"""

import os
from os.path import join as pjoin, exists, isfile, basename, realpath, splitext
import shutil

from wheel.install import WheelFile

from ..wheeltools import (rewrite_record, InWheel, InWheelCtx, WheelToolsError,
                          add_platforms)
from ..tmpdirs import InTemporaryDirectory
from ..tools import zip2dir

from nose.tools import (assert_true, assert_false, assert_raises, assert_equal)

from .test_wheelies import PURE_WHEEL, PLAT_WHEEL


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
    # Test in-wheel context managers
    # Stuff they share
    for ctx_mgr in InWheel, InWheelCtx:
        with ctx_mgr(PURE_WHEEL): # No output wheel
            shutil.rmtree('fakepkg2')
            res = sorted(os.listdir('.'))
        assert_equal(res, ['fakepkg2-1.0.dist-info'])
        # The original wheel unchanged
        with ctx_mgr(PURE_WHEEL): # No output wheel
            res = sorted(os.listdir('.'))
        assert_equal(res, ['fakepkg2', 'fakepkg2-1.0.dist-info'])
        # Make an output wheel file in a temporary directory
        with InTemporaryDirectory():
            mod_path = pjoin('fakepkg2', 'module1.py')
            with ctx_mgr(PURE_WHEEL, 'mungled.whl'):
                assert_true(isfile(mod_path))
                os.unlink(mod_path)
            with ctx_mgr('mungled.whl'):
                assert_false(isfile(mod_path))
    # Different return from context manager
    with InWheel(PURE_WHEEL) as wheel_path:
        assert_equal(realpath(wheel_path), realpath(os.getcwd()))
    with InWheelCtx(PURE_WHEEL) as ctx:
        assert_equal(realpath(ctx.wheel_path), realpath(os.getcwd()))
    # Set the output wheel inside the with block
    with InTemporaryDirectory() as tmpdir:
        mod_path = pjoin('fakepkg2', 'module1.py')
        with InWheelCtx(PURE_WHEEL) as ctx:
            assert_true(isfile(mod_path))
            os.unlink(mod_path)
            # Set output name in context manager, so write on output
            ctx.out_wheel = pjoin(tmpdir, 'mungled.whl')
        with InWheel('mungled.whl'):
            assert_false(isfile(mod_path))


def get_winfo(info_fname, drop_version=True):
    """ Get wheel info from WHEEL file

    Drop "Wheel-Version" by default in case this changes in the future
    """
    wf = WheelFile(info_fname)
    info = sorted(wf.parsed_wheel_info.items())
    if drop_version:
        info = [(name, value) for (name, value) in info
                if name != "Wheel-Version"]
    return info


def test_add_platforms():
    # Check adding platform to wheel name and tag section
    exp_items = [('Generator', 'bdist_wheel (0.23.0)'),
                 ('Root-Is-Purelib', 'false'),
                 ('Tag', 'cp27-none-macosx_10_6_intel'),
                 ('Wheel-Version', '1.0')]
    assert_equal(get_winfo(PLAT_WHEEL, drop_version=False), exp_items)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        plats = ('macosx_10_9_intel', 'macosx_10_9_x86_64')
        # Can't add platforms to a pure wheel
        assert_raises(WheelToolsError,
                      add_platforms, PURE_WHEEL, plats, tmpdir)
        assert_false(exists(out_fname))
        out_fname = ('fakepkg1-1.0-cp27-none-macosx_10_6_intel.'
                     'macosx_10_9_intel.macosx_10_9_x86_64.whl')
        assert_equal(realpath(add_platforms(PLAT_WHEEL, plats, tmpdir)),
                     realpath(out_fname))
        assert_true(isfile(out_fname))
        # Expected output minus wheel-version (that might change)
        extra_exp = [('Generator', 'bdist_wheel (0.23.0)'),
                      ('Root-Is-Purelib', 'false'),
                      ('Tag', 'cp27-none-macosx_10_6_intel'),
                      ('Tag', 'cp27-none-macosx_10_9_intel'),
                      ('Tag', 'cp27-none-macosx_10_9_x86_64')]
        assert_equal(get_winfo(out_fname), extra_exp)
        # If wheel exists (as it does) then raise error
        assert_raises(WheelToolsError,
                      add_platforms, PLAT_WHEEL, plats, tmpdir)
        # Unless clobber is set, no error
        add_platforms(PLAT_WHEEL, plats, tmpdir, clobber=True)
        # Assemble platform tags in two waves to check tags are not being
        # multiplied
        out_1 = 'fakepkg1-1.0-cp27-none-macosx_10_6_intel.macosx_10_9_intel.whl'
        assert_equal(realpath(add_platforms(PLAT_WHEEL, plats[0:1], tmpdir)),
                     realpath(out_1))
        assert_equal(get_winfo(out_1), extra_exp[:-1])
        out_2 = splitext(out_1)[0] + '.macosx_10_9_x86_64.whl'
        assert_equal(realpath(add_platforms(out_1, plats[1:], tmpdir, True)),
                     realpath(out_2))
        assert_equal(get_winfo(out_2), extra_exp)
        # Default is to write into directory of wheel
        os.mkdir('wheels')
        shutil.copy2(PLAT_WHEEL, 'wheels')
        local_plat = pjoin('wheels', basename(PLAT_WHEEL))
        local_out = pjoin('wheels', out_fname)
        add_platforms(local_plat, plats)
        assert_true(exists(local_out))
        assert_raises(WheelToolsError, add_platforms, local_plat, plats)
        add_platforms(local_plat, plats, clobber=True)
        # If platforms already present, don't write more
        res = sorted(os.listdir('wheels'))
        assert_equal(add_platforms(local_out, plats, clobber=True), None)
        assert_equal(sorted(os.listdir('wheels')), res)
        assert_equal(get_winfo(out_fname), extra_exp)
        # But WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        add_platforms(local_out, plats, clobber=True)
        assert_equal(sorted(os.listdir('wheels')), res)
        assert_equal(get_winfo(out_fname), extra_exp)

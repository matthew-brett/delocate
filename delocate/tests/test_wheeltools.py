""" Tests for wheeltools utilities
"""

import os
from os.path import join as pjoin, exists, isfile, basename, realpath, splitext
import shutil

try:
    from wheel.install import WheelFile
except ImportError:  # As of Wheel 0.32.0
    from wheel.wheelfile import WheelFile

from ..wheeltools import (rewrite_record, InWheel, InWheelCtx, WheelToolsError,
                          add_platforms, _get_wheelinfo_name)
from ..tmpdirs import InTemporaryDirectory
from ..tools import zip2dir, open_readable

from .pytest_tools import (assert_true, assert_false, assert_raises,
                           assert_equal)

from .test_wheelies import PURE_WHEEL, PLAT_WHEEL


def assert_record_equal(record_orig, record_new):
    assert_equal(sorted(record_orig.splitlines()),
                 sorted(record_new.splitlines()))


def test_rewrite_record():
    dist_info_sdir = 'fakepkg2-1.0.dist-info'
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, 'wheel')
        record_fname = pjoin('wheel', dist_info_sdir, 'RECORD')
        with open_readable(record_fname, 'rt') as fobj:
            record_orig = fobj.read()
        # Test we get the same record by rewriting
        os.unlink(record_fname)
        rewrite_record('wheel')
        with open_readable(record_fname, 'rt') as fobj:
            record_new = fobj.read()
        assert_record_equal(record_orig, record_new)
        # Test that signature gets deleted
        sig_fname = pjoin('wheel', dist_info_sdir, 'RECORD.jws')
        with open(sig_fname, 'wt') as fobj:
            fobj.write('something')
        rewrite_record('wheel')
        with open_readable(record_fname, 'rt') as fobj:
            record_new = fobj.read()
        assert_record_equal(record_orig, record_new)
        assert_false(exists(sig_fname))
        # Test error for too many dist-infos
        shutil.copytree(pjoin('wheel', dist_info_sdir),
                        pjoin('wheel', 'anotherpkg-2.0.dist-info'))
        assert_raises(WheelToolsError, rewrite_record, 'wheel')


def test_in_wheel():
    # Test in-wheel context managers
    # Stuff they share
    for ctx_mgr in InWheel, InWheelCtx:
        with ctx_mgr(PURE_WHEEL):  # No output wheel
            shutil.rmtree('fakepkg2')
            res = sorted(os.listdir('.'))
        assert_equal(res, ['fakepkg2-1.0.dist-info'])
        # The original wheel unchanged
        with ctx_mgr(PURE_WHEEL):  # No output wheel
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


def _filter_key(items, key):
    return [(k, v) for k, v in items if k != key]


def get_info(wheelfile):
    # Work round wheel API changes
    try:
        return wheelfile.parsed_wheel_info
    except AttributeError:
        pass
    # Wheel 0.32.0
    from wheel.pkginfo import read_pkg_info_bytes
    info_name = _get_wheelinfo_name(wheelfile)
    return read_pkg_info_bytes(wheelfile.read(info_name))


def assert_winfo_similar(whl_fname, exp_items, drop_version=True):
    wf = WheelFile(whl_fname)
    wheel_parts = wf.parsed_filename.groupdict()
    # Info can contain duplicate keys (e.g. Tag)
    w_info = sorted(get_info(wf).items())
    if drop_version:
        w_info = _filter_key(w_info, 'Wheel-Version')
        exp_items = _filter_key(exp_items, 'Wheel-Version')
    assert_equal(len(exp_items), len(w_info))
    # Extract some information from actual values
    wheel_parts['pip_version'] = dict(w_info)['Generator'].split()[1]
    for (key1, value1), (key2, value2) in zip(exp_items, w_info):
        assert_equal(key1, key2)
        value1 = value1.format(**wheel_parts)
        assert_equal(value1, value2)


def test_add_platforms():
    # Check adding platform to wheel name and tag section
    exp_items = [('Generator', 'bdist_wheel {pip_version}'),
                 ('Root-Is-Purelib', 'false'),
                 ('Tag', '{pyver}-{abi}-macosx_10_6_intel'),
                 ('Wheel-Version', '1.0')]
    assert_winfo_similar(PLAT_WHEEL, exp_items, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        plats = ('macosx_10_9_intel', 'macosx_10_9_x86_64')
        # Can't add platforms to a pure wheel
        assert_raises(WheelToolsError,
                      add_platforms, PURE_WHEEL, plats, tmpdir)
        assert_false(exists(out_fname))
        out_fname = (splitext(basename(PLAT_WHEEL))[0] +
                     '.macosx_10_9_intel.macosx_10_9_x86_64.whl')
        assert_equal(realpath(add_platforms(PLAT_WHEEL, plats, tmpdir)),
                     realpath(out_fname))
        assert_true(isfile(out_fname))
        # Expected output minus wheel-version (that might change)
        extra_exp = [('Generator', 'bdist_wheel {pip_version}'),
                     ('Root-Is-Purelib', 'false'),
                     ('Tag', '{pyver}-{abi}-macosx_10_6_intel'),
                     ('Tag', '{pyver}-{abi}-macosx_10_9_intel'),
                     ('Tag', '{pyver}-{abi}-macosx_10_9_x86_64')]
        assert_winfo_similar(out_fname, extra_exp)
        # If wheel exists (as it does) then raise error
        assert_raises(WheelToolsError,
                      add_platforms, PLAT_WHEEL, plats, tmpdir)
        # Unless clobber is set, no error
        add_platforms(PLAT_WHEEL, plats, tmpdir, clobber=True)
        # Assemble platform tags in two waves to check tags are not being
        # multiplied
        out_1 = splitext(basename(PLAT_WHEEL))[0] + '.macosx_10_9_intel.whl'
        assert_equal(realpath(add_platforms(PLAT_WHEEL, plats[0:1], tmpdir)),
                     realpath(out_1))
        assert_winfo_similar(out_1, extra_exp[:-1])
        out_2 = splitext(out_1)[0] + '.macosx_10_9_x86_64.whl'
        assert_equal(realpath(add_platforms(out_1, plats[1:], tmpdir, True)),
                     realpath(out_2))
        assert_winfo_similar(out_2, extra_exp)
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
        assert_winfo_similar(out_fname, extra_exp)
        # But WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        add_platforms(local_out, plats, clobber=True)
        assert_equal(sorted(os.listdir('wheels')), res)
        assert_winfo_similar(out_fname, extra_exp)

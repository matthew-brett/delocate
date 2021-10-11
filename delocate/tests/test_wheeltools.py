""" Tests for wheeltools utilities
"""

import os
import shutil
from os.path import basename, exists, isfile
from os.path import join as pjoin
from os.path import realpath, splitext
from typing import AnyStr

try:
    from wheel.install import WheelFile
except ImportError:  # As of Wheel 0.32.0
    from wheel.wheelfile import WheelFile

from ..tmpdirs import InTemporaryDirectory
from ..tools import open_readable, zip2dir
from ..wheeltools import (
    InWheel,
    InWheelCtx,
    WheelToolsError,
    _get_wheelinfo_name,
    add_platforms,
    rewrite_record,
)
from .pytest_tools import assert_equal, assert_false, assert_raises, assert_true
from .test_wheelies import PLAT_WHEEL, PURE_WHEEL

# Template for testing expected wheel information
EXP_PLAT = splitext(PLAT_WHEEL)[0].split("-")[-1]
EXP_ITEMS = [
    ("Generator", "bdist_wheel {pip_version}"),
    ("Root-Is-Purelib", "false"),
    ("Tag", "{pyver}-{abi}-" + EXP_PLAT),
    ("Wheel-Version", "1.0"),
]
# Extra platforms to add
EXTRA_PLATS = ("macosx_10_11_universal2", "macosx_10_11_x86_64")
# Expected outputs for plat added wheels minus wheel-version (that might
# change)
EXTRA_EXPS = [
    ("Generator", "bdist_wheel {pip_version}"),
    ("Root-Is-Purelib", "false"),
] + [("Tag", "{pyver}-{abi}-" + plat) for plat in (EXP_PLAT,) + EXTRA_PLATS]


def assert_record_equal(record_orig: AnyStr, record_new: AnyStr) -> None:
    assert sorted(record_orig.splitlines()) == sorted(record_new.splitlines())


def test_rewrite_record():
    dist_info_sdir = "fakepkg2-1.0.dist-info"
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "wheel")
        record_fname = pjoin("wheel", dist_info_sdir, "RECORD")
        with open_readable(record_fname, "rt") as fobj:
            record_orig = fobj.read()
        # Test we get the same record by rewriting
        os.unlink(record_fname)
        rewrite_record("wheel")
        with open_readable(record_fname, "rt") as fobj:
            record_new = fobj.read()
        assert_record_equal(record_orig, record_new)
        # Test that signature gets deleted
        sig_fname = pjoin("wheel", dist_info_sdir, "RECORD.jws")
        with open(sig_fname, "wt") as fobj:
            fobj.write("something")
        rewrite_record("wheel")
        with open_readable(record_fname, "rt") as fobj:
            record_new = fobj.read()
        assert_record_equal(record_orig, record_new)
        assert_false(exists(sig_fname))
        # Test error for too many dist-infos
        shutil.copytree(
            pjoin("wheel", dist_info_sdir),
            pjoin("wheel", "anotherpkg-2.0.dist-info"),
        )
        assert_raises(WheelToolsError, rewrite_record, "wheel")


def test_in_wheel():
    # Test in-wheel context managers
    # Stuff they share
    for ctx_mgr in InWheel, InWheelCtx:
        with ctx_mgr(PURE_WHEEL):  # No output wheel
            shutil.rmtree("fakepkg2")
            res = sorted(os.listdir("."))
        assert_equal(res, ["fakepkg2-1.0.dist-info"])
        # The original wheel unchanged
        with ctx_mgr(PURE_WHEEL):  # No output wheel
            res = sorted(os.listdir("."))
        assert_equal(res, ["fakepkg2", "fakepkg2-1.0.dist-info"])
        # Make an output wheel file in a temporary directory
        with InTemporaryDirectory():
            mod_path = pjoin("fakepkg2", "module1.py")
            with ctx_mgr(PURE_WHEEL, "mungled.whl"):
                assert_true(isfile(mod_path))
                os.unlink(mod_path)
            with ctx_mgr("mungled.whl"):
                assert_false(isfile(mod_path))
    # Different return from context manager
    with InWheel(PURE_WHEEL) as wheel_path:
        assert_equal(realpath(wheel_path), realpath(os.getcwd()))
    with InWheelCtx(PURE_WHEEL) as ctx:
        assert_equal(realpath(ctx.wheel_path), realpath(os.getcwd()))
    # Set the output wheel inside the with block
    with InTemporaryDirectory() as tmpdir:
        mod_path = pjoin("fakepkg2", "module1.py")
        with InWheelCtx(PURE_WHEEL) as ctx:
            assert_true(isfile(mod_path))
            os.unlink(mod_path)
            # Set output name in context manager, so write on output
            ctx.out_wheel = pjoin(tmpdir, "mungled.whl")
        with InWheel("mungled.whl"):
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
        w_info = _filter_key(w_info, "Wheel-Version")
        exp_items = _filter_key(exp_items, "Wheel-Version")
    assert_equal(len(exp_items), len(w_info))
    # Extract some information from actual values
    wheel_parts["pip_version"] = dict(w_info)["Generator"].split()[1]
    for (key1, value1), (key2, value2) in zip(
        sorted(exp_items), sorted(w_info)
    ):
        assert_equal(key1, key2)
        value1 = value1.format(**wheel_parts)
        assert_equal(value1, value2)


def test_add_platforms():
    # Check adding platform to wheel name and tag section
    assert_winfo_similar(PLAT_WHEEL, EXP_ITEMS, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Can't add platforms to a pure wheel
        assert_raises(
            WheelToolsError, add_platforms, PURE_WHEEL, EXTRA_PLATS, tmpdir
        )
        assert_false(exists(out_fname))
        out_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],) + EXTRA_PLATS + ("whl",)
        )
        actual_fname = realpath(add_platforms(PLAT_WHEEL, EXTRA_PLATS, tmpdir))
        assert_equal(actual_fname, realpath(out_fname))
        assert_true(isfile(out_fname))
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # If wheel exists (as it does) then raise error
        assert_raises(
            WheelToolsError, add_platforms, PLAT_WHEEL, EXTRA_PLATS, tmpdir
        )
        # Unless clobber is set, no error
        add_platforms(PLAT_WHEEL, EXTRA_PLATS, tmpdir, clobber=True)
        # Assemble platform tags in two waves to check tags are not being
        # multiplied
        start = PLAT_WHEEL
        exp_end = len(EXTRA_EXPS) - len(EXTRA_PLATS) + 1
        for i, extra_plat in enumerate(EXTRA_PLATS):
            out = ".".join(
                (splitext(basename(start))[0],) + (extra_plat, "whl")
            )
            back = add_platforms(start, [extra_plat], tmpdir, clobber=True)
            assert_equal(realpath(back), realpath(out))
            assert_winfo_similar(out, EXTRA_EXPS[: exp_end + i])
            start = out
        # Default is to write into directory of wheel
        os.mkdir("wheels")
        shutil.copy2(PLAT_WHEEL, "wheels")
        local_plat = pjoin("wheels", basename(PLAT_WHEEL))
        local_out = pjoin("wheels", out_fname)
        add_platforms(local_plat, EXTRA_PLATS)
        assert_true(exists(local_out))
        assert_raises(WheelToolsError, add_platforms, local_plat, EXTRA_PLATS)
        add_platforms(local_plat, EXTRA_PLATS, clobber=True)
        # If platforms already present, don't write more
        res = sorted(os.listdir("wheels"))
        assert_equal(add_platforms(local_out, EXTRA_PLATS, clobber=True), None)
        assert_equal(sorted(os.listdir("wheels")), res)
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # But WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        add_platforms(local_out, EXTRA_PLATS, clobber=True)
        assert_equal(sorted(os.listdir("wheels")), res)
        assert_winfo_similar(out_fname, EXTRA_EXPS)

"""Tests for wheeltools utilities."""

from __future__ import annotations

import os
import re
import shutil
from email.message import Message
from os.path import basename, exists, isfile, realpath, splitext
from os.path import join as pjoin
from pathlib import Path
from typing import AnyStr
from zipfile import ZipFile

import pytest
from packaging.utils import parse_wheel_filename

from delocate.pkginfo import read_pkg_info_bytes

from ..tmpdirs import InTemporaryDirectory
from ..tools import open_readable, zip2dir
from ..wheeltools import (
    InWheel,
    InWheelCtx,
    WheelToolsError,
    add_platforms,
    rewrite_record,
)
from .pytest_tools import assert_equal, assert_false, assert_raises, assert_true
from .test_wheelies import PLAT_WHEEL, PURE_WHEEL

# Non-greedy matching of an optional build number may be too clever (more
# invalid wheel filenames will match). Separate regex for .dist-info?
# Copied from wheel.wheelfile
WHEEL_INFO_RE = re.compile(
    r"""^(?P<namever>(?P<name>.+?)-(?P<ver>.+?))(-(?P<build>\d[^-]*))?
     -(?P<pyver>.+?)-(?P<abi>.+?)-(?P<plat>.+?)\.whl$""",
    re.VERBOSE,
)

# Template for testing expected wheel information
EXP_PLAT = splitext(PLAT_WHEEL)[0].split("-")[-1]
EXP_ITEMS = [
    ("Generator", "{generator_tool_version}"),
    ("Root-Is-Purelib", "false"),
    ("Tag", "{pyver}-{abi}-" + EXP_PLAT),
    ("Wheel-Version", "1.0"),
]
# Extra platforms to add
EXTRA_PLATS = ("macosx_10_11_universal2", "macosx_10_11_x86_64")
# Expected outputs for plat added wheels minus wheel-version (that might
# change)
EXTRA_EXPS = [
    ("Generator", "{generator_tool_version}"),
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
        with open(sig_fname, "w") as fobj:
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


def _filter_key(
    items: list[tuple[str, str]], key: str
) -> list[tuple[str, str]]:
    """Return a list of key/value pairs with any instances of `key` removed."""
    return [(k, v) for k, v in items if k != key]


def get_info(wheel_path: str | os.PathLike[str]) -> Message:
    """Return the `.dist-info/WHEEL` metadata from `wheel_path`."""
    wheel_path = Path(wheel_path)
    name, version, _, _ = parse_wheel_filename(wheel_path.name)
    with ZipFile(wheel_path) as zip_file:
        return read_pkg_info_bytes(
            zip_file.read(f"{name}-{version}.dist-info/WHEEL")
        )


def assert_winfo_similar(
    wheel_path: str | os.PathLike[str],
    expected: list[tuple[str, str]],
    drop_version: bool = True,
) -> None:
    """Assert `wheel_path` has `.dist-info/WHEEL` items matching `expected`.

    Skips `Wheel-Version` check if `drop_version` is True.
    """
    wheel_path = Path(wheel_path)
    match = WHEEL_INFO_RE.match(wheel_path.name)
    assert match
    wheel_parts = match.groupdict()
    # Info can contain duplicate keys (e.g. Tag)
    wheel_info: list[tuple[str, str]] = get_info(wheel_path).items()
    if drop_version:
        wheel_info = _filter_key(wheel_info, "Wheel-Version")
        expected = _filter_key(expected, "Wheel-Version")
    # Extract some information from actual values
    wheel_parts["generator_tool_version"] = dict(wheel_info)["Generator"]
    # Apply variable metadata to expected items
    expected = [(k, v.format(**wheel_parts)) for k, v in expected]
    assert sorted(wheel_info) == sorted(expected)


def test_add_platforms() -> None:
    # Check adding platform to wheel name and tag section
    assert_winfo_similar(PLAT_WHEEL, EXP_ITEMS, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Can't add platforms to a pure wheel
        with pytest.raises(WheelToolsError):
            add_platforms(PURE_WHEEL, EXTRA_PLATS, tmpdir)
        assert not exists(out_fname)
        out_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],) + EXTRA_PLATS + ("whl",)
        )
        actual_fname = realpath(add_platforms(PLAT_WHEEL, EXTRA_PLATS, tmpdir))
        assert actual_fname == realpath(out_fname)
        assert isfile(out_fname)
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # If wheel exists (as it does) then raise error

        with pytest.raises(WheelToolsError):
            add_platforms(PLAT_WHEEL, EXTRA_PLATS, tmpdir)
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
            assert realpath(back) == realpath(out)
            assert_winfo_similar(out, EXTRA_EXPS[: exp_end + i])
            start = out
        # Default is to write into directory of wheel
        os.mkdir("wheels")
        shutil.copy2(PLAT_WHEEL, "wheels")
        local_plat = pjoin("wheels", basename(PLAT_WHEEL))
        local_out = pjoin("wheels", out_fname)
        add_platforms(local_plat, EXTRA_PLATS)
        assert exists(local_out)
        with pytest.raises(WheelToolsError):
            add_platforms(local_plat, EXTRA_PLATS)
        add_platforms(local_plat, EXTRA_PLATS, clobber=True)
        # If platforms already present, don't write more
        res = sorted(os.listdir("wheels"))
        assert add_platforms(local_out, EXTRA_PLATS, clobber=True) is None
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # But WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        add_platforms(local_out, EXTRA_PLATS, clobber=True)
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(out_fname, EXTRA_EXPS)

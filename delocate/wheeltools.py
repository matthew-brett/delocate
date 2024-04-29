"""General tools for working with wheels.

Tools that aren't specific to delocation.
"""

from __future__ import annotations

import base64
import csv
import glob
import hashlib
import os
import sys
from itertools import product
from os import PathLike
from os.path import abspath, basename, dirname, exists, relpath, splitext
from os.path import join as pjoin
from os.path import sep as psep
from typing import Iterable, Optional, Union, overload

from packaging.utils import parse_wheel_filename

from delocate.pkginfo import read_pkg_info, write_pkg_info

from .tmpdirs import InTemporaryDirectory
from .tools import dir2zip, open_rw, unique_by_index, zip2dir


class WheelToolsError(Exception):
    """Errors raised when reading or writing wheel files."""


def _open_for_csv(name, mode):
    """Deal with Python 2/3 open API differences."""
    if sys.version_info[0] < 3:
        return open_rw(name, mode + "b")
    return open_rw(name, mode, newline="", encoding="utf-8")


def rewrite_record(bdist_dir: str | PathLike) -> None:
    """Rewrite RECORD file with hashes for all files in `wheel_sdir`.

    Copied from :method:`wheel.bdist_wheel.bdist_wheel.write_record`.

    Will also unsign wheel.

    Parameters
    ----------
    bdist_dir : str or Path-like
        Path of unpacked wheel file
    """
    info_dirs = glob.glob(pjoin(bdist_dir, "*.dist-info"))
    if len(info_dirs) != 1:
        raise WheelToolsError("Should be exactly one `*.dist_info` directory")
    record_path = pjoin(info_dirs[0], "RECORD")
    record_relpath = relpath(record_path, bdist_dir)
    # Unsign wheel - because we're invalidating the record hash
    sig_path = pjoin(info_dirs[0], "RECORD.jws")
    if exists(sig_path):
        os.unlink(sig_path)

    def walk():
        for dir, dirs, files in os.walk(bdist_dir):
            for f in files:
                yield pjoin(dir, f)

    def skip(path):
        """Wheel hashes every possible file."""
        return path == record_relpath

    with _open_for_csv(record_path, "w+") as record_file:
        writer = csv.writer(record_file)
        for path in walk():
            relative_path = relpath(path, bdist_dir)
            if skip(relative_path):
                hash = ""
                size: Union[int, str] = ""
            else:
                with open(path, "rb") as f:
                    data = f.read()
                digest = hashlib.sha256(data).digest()
                hash = "sha256=%s" % (
                    base64.urlsafe_b64encode(digest).decode("ascii").strip("=")
                )
                size = len(data)
            path_for_record = relpath(path, bdist_dir).replace(psep, "/")
            writer.writerow((path_for_record, hash, size))


class InWheel(InTemporaryDirectory):
    """Context manager for doing things inside wheels.

    On entering, you'll find yourself in the root tree of the wheel.  If you've
    asked for an output wheel, then on exit we'll rewrite the wheel record and
    pack stuff up for you.
    """

    def __init__(self, in_wheel, out_wheel=None, ret_self=False):
        """Initialize in-wheel context manager.

        Parameters
        ----------
        in_wheel : str
            filename of wheel to unpack and work inside
        out_wheel : None or str:
            filename of wheel to write after exiting.  If None, don't write and
            discard
        ret_self : bool, optional
            If True, return ``self`` from ``__enter__``, otherwise return the
            directory path.
        """
        self.in_wheel = abspath(in_wheel)
        self.out_wheel = None if out_wheel is None else abspath(out_wheel)
        super(InWheel, self).__init__()

    def __enter__(self):
        """Unpack a wheel and return the path to its temporary directly.

        Will also chdir to the temporary directory.
        """
        zip2dir(self.in_wheel, self.name)
        return super(InWheel, self).__enter__()

    def __exit__(self, exc, value, tb):
        """Write out the wheel based on the value of `out_wheel`, then cleanup.

        Reverts the working directory and deletes the temporary directory.
        """
        if self.out_wheel is not None:
            rewrite_record(self.name)
            dir2zip(self.name, self.out_wheel)
        return super(InWheel, self).__exit__(exc, value, tb)


class InWheelCtx(InWheel):
    """Context manager for doing things inside wheels.

    On entering, you'll find yourself in the root tree of the wheel.  If you've
    asked for an output wheel, then on exit we'll rewrite the wheel record and
    pack stuff up for you.

    The context manager returns itself from the __enter__ method, so you can
    set things like ``out_wheel``.  This is useful when processing in the wheel
    will dictate what the output wheel name is, or whether you want to save at
    all.

    The current path of the wheel contents is set in the attribute
    ``wheel_path``.
    """

    def __init__(self, in_wheel, out_wheel=None):
        """Init in-wheel context manager returning self from enter.

        Parameters
        ----------
        in_wheel : str
            filename of wheel to unpack and work inside
        out_wheel : None or str:
            filename of wheel to write after exiting.  If None, don't write and
            discard
        """
        super(InWheelCtx, self).__init__(in_wheel, out_wheel)
        self.wheel_path = None

    def __enter__(self):
        # NOTICE: this method breaks the Liskov substitution principle.
        """Unpack a wheel to a temporary directory and return self.

        Will also chdir to the temporary directory.
        """
        self.wheel_path = super(InWheelCtx, self).__enter__()
        return self


@overload
def add_platforms(
    in_wheel: str,
    platforms: Iterable[str],
    out_path: str,
    clobber: bool = False,
) -> str: ...


@overload
def add_platforms(
    in_wheel: str,
    platforms: Iterable[str],
    out_path: None = None,
    clobber: bool = False,
) -> None: ...


def add_platforms(
    in_wheel: str,
    platforms: Iterable[str],
    out_path: Optional[str] = None,
    clobber: bool = False,
) -> Optional[str]:
    """Add platform tags `platforms` to `in_wheel` filename and WHEEL tags.

    Add any platform tags in `platforms` that are missing from `in_wheel`
    filename.

    Add any platform tags in `platforms` that are missing from `in_wheel`
    ``WHEEL`` file.

    Parameters
    ----------
    in_wheel : str
        Filename of wheel to which to add platform tags
    platforms : iterable
        platform tags to add to wheel filename and WHEEL tags - e.g.
        ``('macosx_10_9_intel', 'macosx_10_9_x86_64')
    out_path : None or str, optional
        Directory to which to write new wheel.  Default is directory containing
        `in_wheel`
    clobber : bool, optional
        If True, overwrite existing output filename, otherwise raise error

    Returns
    -------
    out_wheel : None or str
        Absolute path of wheel file written, or None if no wheel file written.
    """
    in_wheel = abspath(in_wheel)
    out_path = dirname(in_wheel) if out_path is None else abspath(out_path)
    name, version, _, tags = parse_wheel_filename(basename(in_wheel))
    info_fname = f"{name}-{version}.dist-info/WHEEL"

    # Check what tags we have
    platform_tags = {tag.platform for tag in tags}
    extra_fname_tags = [tag for tag in platforms if tag not in platform_tags]
    in_wheel_base, ext = splitext(basename(in_wheel))
    out_wheel_base = ".".join([in_wheel_base] + extra_fname_tags)
    out_wheel = pjoin(out_path, out_wheel_base + ext)
    if exists(out_wheel) and not clobber:
        raise WheelToolsError(
            "Not overwriting {0}; set clobber=True to overwrite".format(
                out_wheel
            )
        )
    with InWheelCtx(in_wheel) as ctx:
        info = read_pkg_info(info_fname)
        if info["Root-Is-Purelib"] == "true":
            raise WheelToolsError("Cannot add platforms to pure wheel")
        in_info_tags = [tag for name, tag in info.items() if name == "Tag"]
        # Python version, C-API version combinations
        pyc_apis = ["-".join(tag.split("-")[:2]) for tag in in_info_tags]
        # unique Python version, C-API version combinations
        pyc_apis = unique_by_index(pyc_apis)
        # Add new platform tags for each Python version, C-API combination
        required_tags = ["-".join(tup) for tup in product(pyc_apis, platforms)]
        needs_write = False
        for req_tag in required_tags:
            if req_tag in in_info_tags:
                continue
            needs_write = True
            info.add_header("Tag", req_tag)
        if needs_write:
            write_pkg_info(info_fname, info)
            # Tell context manager to write wheel on exit by setting filename
            ctx.out_wheel = out_wheel
    return ctx.out_wheel

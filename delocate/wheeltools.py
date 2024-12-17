"""General tools for working with wheels.

Tools that aren't specific to delocation.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import os
from collections.abc import Iterable, Iterator
from itertools import product
from os import PathLike
from os.path import abspath, basename, dirname, exists, splitext
from os.path import join as pjoin
from pathlib import Path, PurePosixPath
from typing import overload

from packaging.utils import parse_wheel_filename

from delocate.pkginfo import read_pkg_info, write_pkg_info

from .tmpdirs import InTemporaryDirectory
from .tools import _unique_everseen, dir2zip, zip2dir


class WheelToolsError(Exception):
    """Errors raised when reading or writing wheel files."""


def rewrite_record(bdist_dir: str | PathLike[str]) -> None:
    """Rewrite RECORD file with hashes for all files in `wheel_sdir`.

    Copied from :method:`wheel.bdist_wheel.bdist_wheel.write_record`.

    Will also unsign wheel.

    Parameters
    ----------
    bdist_dir : str or Path-like
        Path of unpacked wheel file
    """
    bdist_dir = Path(bdist_dir).resolve(strict=True)
    try:
        (info_dir,) = bdist_dir.glob("*.dist-info")
    except ValueError:
        msg = "Should be exactly one `*.dist_info` directory"
        raise WheelToolsError(msg) from None
    record_path = info_dir / "RECORD"
    # Unsign wheel - because we're invalidating the record hash
    Path(info_dir, "RECORD.jws").unlink(missing_ok=True)

    def walk() -> Iterator[tuple[Path, str]]:
        """Walk `(path, relative_posix_str)` for each file in `bdist_dir`."""
        for dirpath_, _dirnames, filenames in os.walk(bdist_dir):
            dirpath = Path(dirpath_).resolve()
            for file in filenames:
                path = dirpath / file
                yield path, str(PurePosixPath(path.relative_to(bdist_dir)))

    with record_path.open("w+", encoding="utf-8", newline="") as record_file:
        writer = csv.writer(record_file)
        for path, relative_path_for_record in walk():
            if path == record_path:
                hash = ""
                size: int | str = ""
            else:
                data = path.read_bytes()
                digest = hashlib.sha256(data).digest()
                hash = "sha256={}".format(
                    base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
                )
                size = len(data)
            writer.writerow((relative_path_for_record, hash, size))


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
        super().__init__()

    def __enter__(self):
        """Unpack a wheel and return the path to its temporary directly.

        Will also chdir to the temporary directory.
        """
        zip2dir(self.in_wheel, self.name)
        return super().__enter__()

    def __exit__(self, exc, value, tb):
        """Write out the wheel based on the value of `out_wheel`, then cleanup.

        Reverts the working directory and deletes the temporary directory.
        """
        if self.out_wheel is not None:
            rewrite_record(self.name)
            dir2zip(self.name, self.out_wheel)
        return super().__exit__(exc, value, tb)


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
        super().__init__(in_wheel, out_wheel)
        self.wheel_path = None

    def __enter__(self):
        # NOTICE: this method breaks the Liskov substitution principle.
        """Unpack a wheel to a temporary directory and return self.

        Will also chdir to the temporary directory.
        """
        self.wheel_path = super().__enter__()
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
    out_path: str | None = None,
    clobber: bool = False,
) -> str | None:
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
            f"Not overwriting {out_wheel}; set clobber=True to overwrite"
        )
    with InWheelCtx(in_wheel) as ctx:
        info = read_pkg_info(info_fname)
        if info["Root-Is-Purelib"] == "true":
            raise WheelToolsError("Cannot add platforms to pure wheel")
        in_info_tags = [tag for name, tag in info.items() if name == "Tag"]
        # Python version, C-API version combinations
        pyc_apis = ["-".join(tag.split("-")[:2]) for tag in in_info_tags]
        # unique Python version, C-API version combinations
        pyc_apis = list(_unique_everseen(pyc_apis))
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

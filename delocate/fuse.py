"""Utilities to fuse trees and wheels.

To "fuse" is to merge two binary libraries of different architectures - see
func:`delocate.tools.lipo_fuse`.

The procedure for fusing two trees (or trees in wheels) is similar to updating
a dictionary.  There is a lhs of an update (fuse) called ``to_tree`` and a rhs
called ``from_tree``.  All files present in ``from_tree`` get copied into
``to_tree``, unless [the file is a library AND there is a corresponding file
with the same relative path in ``to_tree``]. In this case the two files are
"fused" - meaning we use ``lipo_fuse`` to merge the architectures in the two
libraries.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from os import PathLike
from os.path import exists, relpath, splitext
from os.path import join as pjoin
from pathlib import Path

from packaging.utils import parse_wheel_filename

from .delocating import _check_and_update_wheel_name, _update_wheelfile
from .tools import (
    chmod_perms,
    cmp_contents,
    dir2zip,
    lipo_fuse,
    open_rw,
    zip2dir,
)
from .wheeltools import rewrite_record


def _copyfile(in_fname, out_fname):
    # Copies files without read / write permission
    perms = chmod_perms(in_fname)
    with open_rw(in_fname, "rb") as fobj:
        contents = fobj.read()
    with open_rw(out_fname, "wb") as fobj:
        fobj.write(contents)
    os.chmod(out_fname, perms)


def _retag_wheel(to_wheel: Path, from_wheel: Path, to_tree: Path) -> str:
    """Update the name and dist-info to reflect a univeral2 wheel.

    Parameters
    ----------
    to_wheel : Path
        The path of the wheel to fuse into.
    from_wheel : Path
        The path of the wheel to fuse from.
    to_tree : Path
        The path of the directory tree to fuse into (update into).

    Returns
    -------
    retag_name : str
        The new, retagged name the out wheel should be.
    """
    to_tree = to_tree.resolve()
    # Add from_wheel platform tags onto to_wheel filename, but make sure to not
    # add a tag if it is already there
    from_wheel_tags = parse_wheel_filename(from_wheel.name)[-1]
    to_wheel_tags = parse_wheel_filename(to_wheel.name)[-1]
    add_platform_tags = (
        f".{tag.platform}" for tag in from_wheel_tags - to_wheel_tags
    )
    retag_name = to_wheel.stem + "".join(add_platform_tags) + ".whl"

    retag_name = _check_and_update_wheel_name(
        Path(retag_name), to_tree, None
    ).name

    _update_wheelfile(to_tree, retag_name)

    return retag_name


def fuse_trees(
    to_tree: str | PathLike,
    from_tree: str | PathLike,
    lib_exts=(".so", ".dylib", ".a"),
):
    """Fuse path `from_tree` into path `to_tree`.

    For each file in `from_tree` - check for library file extension (in
    `lib_exts` - if present, check if there is a file with matching relative
    path in `to_tree`, if so, use :func:`delocate.tools.lipo_fuse` to fuse the
    two libraries together and write into `to_tree`.  If any of these
    conditions are not met, just copy the file from `from_tree` to `to_tree`.

    Parameters
    ----------
    to_tree : str or Path-like
        path of tree to fuse into (update into)
    from_tree : str or Path-like
        path of tree to fuse from (update from)
    lib_exts : sequence, optional
        filename extensions for libraries
    """
    for from_dirpath, dirnames, filenames in os.walk(Path(from_tree)):
        to_dirpath = pjoin(to_tree, relpath(from_dirpath, from_tree))
        # Copy any missing directories in to_path
        for dirname in tuple(dirnames):
            to_path = pjoin(to_dirpath, dirname)
            if not exists(to_path):
                from_path = pjoin(from_dirpath, dirname)
                shutil.copytree(from_path, to_path)
                # If copying, don't further analyze this directory
                dirnames.remove(dirname)
        for fname in filenames:
            root, ext = splitext(fname)
            from_path = pjoin(from_dirpath, fname)
            to_path = pjoin(to_dirpath, fname)
            if not exists(to_path):
                _copyfile(from_path, to_path)
            elif cmp_contents(from_path, to_path):
                pass
            elif ext in lib_exts:
                # existing lib that needs fuse
                lipo_fuse(from_path, to_path, to_path)
            else:
                # existing not-lib file not identical to source
                _copyfile(from_path, to_path)


def fuse_wheels(
    to_wheel: str | PathLike,
    from_wheel: str | PathLike,
    out_wheel: str | PathLike,
) -> Path:
    """Fuse `from_wheel` into `to_wheel`, write to `out_wheel`.

    Parameters
    ----------
    to_wheel : str or Path-like
        The path of the wheel to fuse into.
    from_wheel : str or Path-like
        The path of the wheel to fuse from.
    out_wheel : str or Path-like
        The path of the new wheel from fusion of `to_wheel` and `from_wheel`. If
        a full path is given, (including the filename) it will be used as is. If
        a directory is given, the fused wheel will be stored in the directory,
        with the name of the wheel automatically determined.

    Returns
    -------
    out_wheel : Path
        The path of the new wheel from fusion of `to_wheel` and `from_wheel`.

    .. versionchanged:: 0.12
        `out_wheel` can now take a directory or None.
    """
    to_wheel = Path(to_wheel).resolve(strict=True)
    from_wheel = Path(from_wheel).resolve(strict=True)
    out_wheel = Path(out_wheel)
    with tempfile.TemporaryDirectory() as temp_dir:
        to_wheel_dir = Path(temp_dir, "to_wheel")
        from_wheel_dir = Path(temp_dir, "from_wheel")
        zip2dir(to_wheel, to_wheel_dir)
        zip2dir(from_wheel, from_wheel_dir)
        fuse_trees(to_wheel_dir, from_wheel_dir)
        if out_wheel.is_dir():
            out_wheel_name = _retag_wheel(to_wheel, from_wheel, to_wheel_dir)
            out_wheel = out_wheel / out_wheel_name
        rewrite_record(to_wheel_dir)
        dir2zip(to_wheel_dir, out_wheel)
    return out_wheel

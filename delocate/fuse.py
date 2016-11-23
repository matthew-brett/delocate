""" Utilities to fuse trees and wheels

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

import shutil

import os
from os.path import (join as pjoin, exists, splitext, relpath, abspath)

from .tools import zip2dir, dir2zip, cmp_contents, lipo_fuse
from .tmpdirs import InTemporaryDirectory
from .wheeltools import rewrite_record


def fuse_trees(to_tree, from_tree, lib_exts=('.so', '.dylib', '.a')):
    """ Fuse path `from_tree` into path `to_tree`

    For each file in `from_tree` - check for library file extension (in
    `lib_exts` - if present, check if there is a file with matching relative
    path in `to_tree`, if so, use :func:`delocate.tools.lipo_fuse` to fuse the
    two libraries together and write into `to_tree`.  If any of these
    conditions are not met, just copy the file from `from_tree` to `to_tree`.

    Parameters
    ---------
    to_tree : str
        path of tree to fuse into (update into)
    from_tree : str
        path of tree to fuse from (update from)
    lib_exts : sequence, optional
        filename extensions for libraries
    """
    for from_dirpath, dirnames, filenames in os.walk(from_tree):
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
                shutil.copyfile(from_path, to_path)
            elif cmp_contents(from_path, to_path):
                pass
            elif ext in lib_exts:
                # existing lib that needs fuse
                lipo_fuse(from_path, to_path, to_path)
            else:
                # existing not-lib file not identical to source
                shutil.copyfile(from_path, to_path)


def fuse_wheels(to_wheel, from_wheel, out_wheel):
    """ Fuse `from_wheel` into `to_wheel`, write to `out_wheel`

    Parameters
    ---------
    to_wheel : str
        filename of wheel to fuse into
    from_wheel : str
        filename of wheel to fuse from
    out_wheel : str
        filename of new wheel from fusion of `to_wheel` and `from_wheel`
    """
    to_wheel, from_wheel, out_wheel = [
        abspath(w) for w in (to_wheel, from_wheel, out_wheel)]
    with InTemporaryDirectory():
        zip2dir(to_wheel, 'to_wheel')
        zip2dir(from_wheel, 'from_wheel')
        fuse_trees('to_wheel', 'from_wheel')
        rewrite_record('to_wheel')
        dir2zip('to_wheel', out_wheel)

""" Routines to manipulate dynamic libraries in trees
"""

from __future__ import division, print_function

from os.path import (join as pjoin, split as psplit, abspath, dirname, basename,
                     exists, relpath)

import shutil

from .tools import add_rpath, set_install_name

class DelocationError(Exception):
    pass


def delocate_tree_libs(lib_dict, lib_path, root_path):
    """ Move needed libraries in `lib_dict` into `lib_path`

    `lib_dict` has keys naming libraries required by the files in the
    corresponding value.  Call the keys, "required libs".  Call the values
    "requiring objects".

    Copy all the required libs to `lib_path`.  Fix up the rpaths and install
    names in the requiring objects to point to these new copies.

    Analyze copied libraries for further required libraries.  Copy these into
    `lib_path`, and fix up copied library rpath / install names.

    Exception: required libs that within the directory tree pointed to by
    `root_path` stay where they are, but we modify requiring objects to use
    relative paths to these libraries.

    Parameters
    ----------
    lib_dict : dict
        dictionary with (key, value) pairs of (install name, set of files in
        tree with install name)
    lib_path : str
        path in which to store copies of libs referred to in keys of
        `lib_dict`.  Assumed to exist
    root_path : str, optional
        root directory of tree analyzed in `lib_dict`.  Any required
        library within the subtrees of `root_path` does not get copied, but
        libraries linking to it have links adjusted to use relative path to
        this library.

    Returns
    -------
    copied_libs : set
        set of names of libraries copied into `lib_path`. Names are filenames
        relative to `lib_path`
    """
    copied_libs = set()
    delocated_libs = set()
    copied_basenames = set()
    # Test for errors first to avoid getting half-way through changing the tree
    for required, requirings in lib_dict.items():
        if required.startswith('@'): # assume @rpath etc are correct
            continue
        r_ed_base = basename(required)
        if relpath(required, root_path).startswith('..'):
            # Not local, plan to copy
            if r_ed_base in copied_basenames:
                raise DelocationError('Already planning to copy library with '
                                      'same basename as: ' + r_ed_base)
            if not exists(required):
                raise DelocationError('library "{0}" does not exist'.format(
                    required))
            copied_libs.add(required)
            copied_basenames.add(r_ed_base)
        else: # Is local, plan to set relative loader_path
            delocated_libs.add(required)
    # Modify in place now that we've checked for errors
    rpathed = set()
    for required in copied_libs:
        shutil.copy2(required, lib_path)
        # Set rpath and install names for this copied library
        for requiring in lib_dict[required]:
            if requiring not in rpathed:
                req_rel = relpath(lib_path, dirname(requiring))
                add_rpath(requiring, '@loader_path/' + req_rel)
                rpathed.add(requiring)
            set_install_name(requiring, required,
                             '@rpath/' + basename(required))
    for required in delocated_libs:
        # Set relative path for local library
        for requiring in lib_dict[required]:
            req_rel = relpath(required, dirname(requiring))
            set_install_name(requiring, required,
                             '@loader_path/' + req_rel)
    return copied_libs

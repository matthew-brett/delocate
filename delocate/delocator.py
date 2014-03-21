""" Routines to manipulate dynamic libaries in trees
"""

from __future__ import division, print_function

from os.path import (join as pjoin, split as psplit, abspath, dirname, basename,
                     exists)


def delocate_tree_libs(lib_dict, lib_path, root_path = None):
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
        path in which to store copies of libs referred to in keys of `lib_dict`
    root_path : None or str, optional
        
    """
    pass

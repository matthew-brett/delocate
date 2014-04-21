""" Analyze libraries in trees

Analyze library dependencies in paths and wheel files
"""

import os
from os.path import join as pjoin, relpath, abspath, isdir, exists

from .tools import (get_install_names, zip2dir, find_package_dirs,
                    get_real_install_names)
from .tmpdirs import InTemporaryDirectory

def tree_libs(start_path, filt_func = None):
    """ Collect unique install names for directory tree `start_path`

    Parameters
    ----------
    start_path : str
        root path of tree to search for install names
    filt_func : None or callable, optional
        If None, inspect all files for install names. If callable, accepts
        filename as argument, returns True if we should inspect the file, False
        otherwise.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (install name, set of files in
        tree with install name)
    """
    lib_dict = {}
    for dirpath, dirnames, basenames in os.walk(start_path):
        for base in basenames:
            fname = pjoin(dirpath, base)
            if not filt_func is None and not filt_func(fname):
                continue
            for install_name in get_real_install_names(fname):
                if install_name in lib_dict:
                    lib_dict[install_name].add(fname)
                else:
                    lib_dict[install_name] = set([fname])
    return lib_dict


def wheel_libs(wheel_fname, lib_filt_func = None):
    """ Collect unique install names from package(s) in wheel file

    Parameters
    ----------
    wheel_fname : str
        Filename of wheel
    lib_filt_func : None or callable, optional
        If None, inspect all files for install names. If callable, accepts
        filename as argument, returns True if we should inspect the file, False
        otherwise.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (install name, set of files in
        wheel packages with install name).  Root directory of wheel package
        appears as current directory in file listing
    """
    wheel_fname = abspath(wheel_fname)
    lib_dict = {}
    with InTemporaryDirectory() as tmpdir:
        zip2dir(wheel_fname, tmpdir)
        for package_path in find_package_dirs('.'):
            pkg_lib_dict = tree_libs(package_path, lib_filt_func)
            for key, values in pkg_lib_dict.items():
                if not key in lib_dict:
                    lib_dict[key] = values
                else:
                    lib_dict[key] += values
    return lib_dict

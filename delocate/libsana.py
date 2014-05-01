""" Analyze libraries in trees

Analyze library dependencies in paths and wheel files
"""

import os
from os.path import join as pjoin, abspath, realpath

from .tools import get_install_names, zip2dir, find_package_dirs
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
        dictionary with (key, value) pairs of (``libpath``,
        ``dependings_dict``).

        ``libpath`` is canonical (``os.path.realpath``) filename of library, or
        library name starting with {'@rpath', '@loader_path',
        '@executable_path'}.

        ``dependings_dict`` is a dict with (key, value) pairs of
        (``depending_libpath``, ``install_name``), where ``dependings_libpath``
        is the canonical (``os.path.realpath``) filename of the library
        depending on ``libpath``, and ``install_name`` is the "install_name" by
        which ``depending_libpath`` refers to ``libpath``.

    Notes
    -----

    See:

    * https://developer.apple.com/library/mac/documentation/Darwin/Reference/ManPages/man1/dyld.1.html
    * http://matthew-brett.github.io/pydagogue/mac_runtime_link.html
    """
    lib_dict = {}
    for dirpath, dirnames, basenames in os.walk(start_path):
        for base in basenames:
            depending_libpath = realpath(pjoin(dirpath, base))
            if not filt_func is None and not filt_func(depending_libpath):
                continue
            for install_name in get_install_names(depending_libpath):
                lib_path = (install_name if install_name.startswith('@')
                            else realpath(install_name))
                if lib_path in lib_dict:
                    lib_dict[lib_path][depending_libpath] = install_name
                else:
                    lib_dict[lib_path] = {depending_libpath: install_name}
    return lib_dict


def strip_lib_dict(lib_dict, strip_prefix):
    """ Return `lib_dict` with `strip_prefix` removed from start of paths

    Use to give form of `lib_dict` that appears relative to some base path
    given by `strip_prefix`.  Particularly useful for analyzing wheels where we
    unpack to a temporary path before analyzing.

    Parameters
    ----------
    lib_dict : dict
        See :func:`tree_libs` for definition.  All depending and depended paths
        are canonical (therefore absolute)
    strip_prefix : str
        Prefix to remove (if present) from all depended and depending library
        paths in `lib_dict`

    Returns
    -------
    relative_dict : dict
        `lib_dict` with `strip_prefix` removed from beginning of all depended
        and depending library paths.
    """
    relative_dict = {}
    n = len(strip_prefix)

    def stripped(path):
        return path if not path.startswith(strip_prefix) else path[n:]

    for lib_path, dependings_dict in lib_dict.items():
        ding_dict = {}
        for depending_libpath, install_name in dependings_dict.items():
            ding_dict[stripped(depending_libpath)] = install_name
        relative_dict[stripped(lib_path)] = ding_dict
    return relative_dict


def wheel_libs(wheel_fname, lib_filt_func = None):
    """ Collect unique install names from package(s) in wheel file

    Use this routine for a dump of the dependency tree.

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

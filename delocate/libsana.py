""" Analyze libraries in trees

Analyze library dependencies in paths and wheel files
"""

import os
from os.path import join as pjoin, realpath

from .tools import get_install_names, zip2dir
from .tmpdirs import TemporaryDirectory

def tree_libs(start_path, filt_func = None):
    """ Return analysis of library dependencies within `start_path`

    Parameters
    ----------
    start_path : str
        root path of tree to search for libraries depending on other libraries.
    filt_func : None or callable, optional
        If None, inspect all files for library dependencies. If callable,
        accepts filename as argument, returns True if we should inspect the
        file, False otherwise.

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


def get_prefix_stripper(strip_prefix):
    """ Return function to strip `strip_prefix` prefix from string if present

    Parameters
    ----------
    prefix : str
        Prefix to strip from the beginning of string if present

    Returns
    -------
    stripper : func
        function such that ``stripper(a_string)`` will strip `prefix` from
        ``a_string`` if present, otherwise pass ``a_string`` unmodified
    """
    n = len(strip_prefix)
    def stripper(path):
        return path if not path.startswith(strip_prefix) else path[n:]
    return stripper


def get_rp_stripper(strip_path):
    """ Return function to strip ``realpath`` of `strip_path` from string

    Parameters
    ----------
    strip_path : str
        path to strip from beginning of strings. Processed to ``strip_prefix``
        by ``realpath(strip_path) + os.path.sep``.

    Returns
    -------
    stripper : func
        function such that ``stripper(a_string)`` will strip ``strip_prefix``
        from ``a_string`` if present, otherwise pass ``a_string`` unmodified
    """
    return get_prefix_stripper(realpath(strip_path) + os.path.sep)


def stripped_lib_dict(lib_dict, strip_prefix):
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
    stripper = get_prefix_stripper(strip_prefix)

    for lib_path, dependings_dict in lib_dict.items():
        ding_dict = {}
        for depending_libpath, install_name in dependings_dict.items():
            ding_dict[stripper(depending_libpath)] = install_name
        relative_dict[stripper(lib_path)] = ding_dict
    return relative_dict


def wheel_libs(wheel_fname, filt_func = None):
    """ Return analysis of library dependencies with a Python wheel

    Use this routine for a dump of the dependency tree.

    Parameters
    ----------
    wheel_fname : str
        Filename of wheel
    filt_func : None or callable, optional
        If None, inspect all files for library dependencies. If callable,
        accepts filename as argument, returns True if we should inspect the
        file, False otherwise.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (``libpath``,
        ``dependings_dict``).  ``libpath`` is library being depended on,
        relative to wheel root path if within wheel tree.  ``dependings_dict``
        is (key, value) of (``depending_lib_path``, ``install_name``).  Again,
        ``depending_lib_path`` is library relative to wheel root path, if
        within wheel tree.
    """
    with TemporaryDirectory() as tmpdir:
        zip2dir(wheel_fname, tmpdir)
        lib_dict = tree_libs(tmpdir, filt_func)
    return stripped_lib_dict(lib_dict, realpath(tmpdir) + os.path.sep)

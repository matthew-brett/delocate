""" Analyze libraries in trees

Analyze library dependencies in paths and wheel files
"""

import os
from os.path import basename, join as pjoin, realpath

import warnings

from .tools import (get_install_names, zip2dir, get_rpaths,
                    get_environment_variable_paths)
from .tmpdirs import TemporaryDirectory


def tree_libs(start_path, filt_func=None):
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

    * https://developer.apple.com/library/mac/documentation/Darwin/Reference/ManPages/man1/dyld.1.html  # noqa: E501
    * http://matthew-brett.github.io/pydagogue/mac_runtime_link.html
    """
    lib_dict = {}
    env_var_paths = get_environment_variable_paths()
    for dirpath, dirnames, basenames in os.walk(start_path):
        for base in basenames:
            depending_libpath = realpath(pjoin(dirpath, base))
            if filt_func is not None and not filt_func(depending_libpath):
                continue
            rpaths = get_rpaths(depending_libpath)
            search_paths = rpaths + env_var_paths
            for install_name in get_install_names(depending_libpath):
                # If the library starts with '@rpath' we'll try and resolve it
                # We'll do nothing to other '@'-paths
                # Otherwise we'll search for the library using env variables
                if install_name.startswith('@rpath'):
                    lib_path = resolve_rpath(install_name, search_paths)
                elif install_name.startswith('@'):
                    lib_path = install_name
                else:
                    lib_path = search_environment_for_lib(install_name)
                if lib_path in lib_dict:
                    lib_dict[lib_path][depending_libpath] = install_name
                else:
                    lib_dict[lib_path] = {depending_libpath: install_name}
    return lib_dict


def resolve_rpath(lib_path, rpaths):
    """ Return `lib_path` with its `@rpath` resolved

    If the `lib_path` doesn't have `@rpath` then it's returned as is.

    If `lib_path` has `@rpath` then returns the first `rpaths`/`lib_path`
    combination found.  If the library can't be found in `rpaths` then a
    detailed warning is printed and `lib_path` is returned as is.

    Parameters
    ----------
    lib_path : str
        The path to a library file, which may or may not start with `@rpath`.
    rpaths : sequence of str
        A sequence of search paths, usually gotten from a call to `get_rpaths`.

    Returns
    -------
    lib_path : str
        A str with the resolved libraries realpath.
    """
    if not lib_path.startswith('@rpath/'):
        return lib_path

    lib_rpath = lib_path.split('/', 1)[1]
    for rpath in rpaths:
        rpath_lib = realpath(pjoin(rpath, lib_rpath))
        if os.path.exists(rpath_lib):
            return rpath_lib

    warnings.warn(
        "Couldn't find {0} on paths:\n\t{1}".format(
            lib_path,
            '\n\t'.join(realpath(path) for path in rpaths),
            )
        )
    return lib_path


def search_environment_for_lib(lib_path):
    """ Search common environment variables for `lib_path`

    We'll use a single approach here:

        1. Search for the basename of the library on DYLD_LIBRARY_PATH
        2. Search for ``realpath(lib_path)``
        3. Search for the basename of the library on DYLD_FALLBACK_LIBRARY_PATH

    This follows the order that Apple defines for "searching for a
    library that has a directory name in it" as defined in their
    documentation here:

    https://developer.apple.com/library/archive/documentation/DeveloperTools/Conceptual/DynamicLibraries/100-Articles/DynamicLibraryUsageGuidelines.html#//apple_ref/doc/uid/TP40001928-SW10

    See the script "testing_osx_rpath_env_variables.sh" in tests/data
    for a more in-depth explanation. The case where LD_LIBRARY_PATH is
    used is a narrow subset of that, so we'll ignore it here to keep
    things simple.

    Parameters
    ----------
    lib_path : str
        Name of the library to search for

    Returns
    -------
    lib_path : str
        Full path of ``basename(lib_path)``'s location, if it can be found, or
        ``realpath(lib_path)`` if it cannot.
    """
    lib_basename = basename(lib_path)
    potential_library_locations = []

    # 1. Search on DYLD_LIBRARY_PATH
    potential_library_locations += _paths_from_var('DYLD_LIBRARY_PATH',
                                                   lib_basename)

    # 2. Search for realpath(lib_path)
    potential_library_locations.append(realpath(lib_path))

    # 3. Search on DYLD_FALLBACK_LIBRARY_PATH
    potential_library_locations += \
        _paths_from_var('DYLD_FALLBACK_LIBRARY_PATH', lib_basename)

    for location in potential_library_locations:
        if os.path.exists(location):
            return location
    return realpath(lib_path)


def get_prefix_stripper(strip_prefix):
    """ Return function to strip `strip_prefix` prefix from string if present

    Parameters
    ----------
    strip_prefix : str
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


def wheel_libs(wheel_fname, filt_func=None):
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


def _paths_from_var(varname, lib_basename):
    var = os.environ.get(varname)
    if var is None:
        return []
    return [pjoin(path, lib_basename) for path in var.split(':')]

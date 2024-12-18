"""Analyze libraries in trees.

Analyze library dependencies in paths and wheel files.
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from collections.abc import Iterable, Iterator
from os import PathLike
from os.path import join as pjoin
from os.path import realpath
from pathlib import Path
from typing import (
    Callable,
)

from typing_extensions import deprecated

from .tmpdirs import TemporaryDirectory
from .tools import (
    _get_install_names,
    _get_rpaths,
    get_environment_variable_paths,
    zip2dir,
)

logger = logging.getLogger(__name__)


class DelocationError(Exception):
    """Generic error for when a problem is encountered during delocation."""


class DependencyNotFound(Exception):
    """Raised by tree_libs or resolve_rpath if an expected dependency is missing."""  # noqa: E501


def _filter_system_libs(libname: str) -> bool:
    return not (libname.startswith("/usr/lib") or libname.startswith("/System"))


def get_dependencies(
    lib_fname: str | PathLike[str],
    executable_path: str | PathLike[str] | None = None,
    filt_func: Callable[[str], bool] = lambda filepath: True,
) -> Iterator[tuple[str | None, str]]:
    """Find and yield the real paths of dependencies of the library `lib_fname`.

    This function is used to search for the real files that are required by
    `lib_fname`.

    The caller must check if any `dependency_path` is None and must decide on
    how to handle missing dependencies.

    Parameters
    ----------
    lib_fname : str or PathLike
        The library to fetch dependencies from.  Must be an existing file.
    executable_path : str or PathLike, optional
        An alternative path to use for resolving `@executable_path`.
    filt_func : callable, optional
        A callable which accepts filename as argument and returns True if we
        should inspect the file or False otherwise.
        Defaults to inspecting all files for library dependencies.
        If `filt_func` returns False for `lib_fname` then no values will be
        yielded.
        If `filt_func` returns False for a dependencies real path then that
        dependency will not be yielded.

    Yields
    ------
    dependency_path : str or None
        The real path of the dependencies of `lib_fname`.
        If the library at `install_name` can not be found then this value will
        be None.
    install_name : str
        The install name of `dependency_path` as if :func:`get_install_names`
        was called.

    Raises
    ------
    DependencyNotFound
        When `lib_fname` does not exist.
    """
    lib_fname = Path(lib_fname)
    if not filt_func(str(lib_fname)):
        logger.debug(f"Ignoring dependencies of {lib_fname}")
        return
    if not lib_fname.is_file():
        if not _filter_system_libs(str(lib_fname)):
            logger.debug(
                "Ignoring missing library %s because it is a system library.",
                lib_fname,
            )
            return
        raise DependencyNotFound(lib_fname)

    environment_paths = get_environment_variable_paths()
    rpaths = {
        arch: [*paths, *environment_paths]
        for arch, paths in _get_rpaths(lib_fname).items()
    }

    install_name_seen = set()
    for arch, install_names in _get_install_names(lib_fname).items():
        for install_name in install_names:
            if install_name in install_name_seen:
                # The same dependency listed by multiple architectures should
                # only be counted once.
                continue
            install_name_seen.add(install_name)
            try:
                if install_name.startswith("@"):
                    dependency_path = resolve_dynamic_paths(
                        install_name,
                        rpaths[arch],
                        loader_path=lib_fname.parent,
                        executable_path=executable_path,
                    )
                else:
                    dependency_path = search_environment_for_lib(install_name)
                if not Path(dependency_path).is_file():
                    if not _filter_system_libs(dependency_path):
                        logger.debug(
                            "Skipped missing dependency %s"
                            " because it is a system library.",
                            dependency_path,
                        )
                    else:
                        raise DependencyNotFound(dependency_path)
                if dependency_path != install_name:
                    logger.debug(
                        "%s resolved to: %s", install_name, dependency_path
                    )
                yield dependency_path, str(install_name)
            except DependencyNotFound:
                message = (
                    f"\n{install_name} not found:\n  Needed by: {lib_fname}"
                )
                if Path(install_name).parts[0] == "@rpath":
                    message += "\n  Search path:\n    " + "\n    ".join(rpaths)
                logger.error(message)
                # At this point install_name is known to be a bad path.
                yield None, str(install_name)


def walk_library(
    lib_fname: str,
    filt_func: Callable[[str], bool] = lambda filepath: True,
    visited: set[str] | None = None,
    executable_path: str | None = None,
) -> Iterator[str]:
    """
    Yield all libraries on which `lib_fname` depends, directly or indirectly.

    First yields `lib_fname` itself, if not already `visited` and then all
    dependencies of `lib_fname`, including dependencies of dependencies.

    Dependencies which can not be resolved will be logged and ignored.

    Parameters
    ----------
    lib_fname : str
        The library to start with.
    filt_func : callable, optional
        A callable which accepts filename as argument and returns True if we
        should inspect the file or False otherwise.
        Defaults to inspecting all files for library dependencies.
        If `filt_func` filters a library it will also exclude all of that
        libraries dependencies as well.
    visited : None or set of str, optional
        We update `visited` with new library_path's as we visit them, to
        prevent infinite recursion and duplicates.  Input value of None
        corresponds to the set `{lib_path}`.  Modified in-place.
    executable_path : str, optional
        An alternative path to use for resolving `@executable_path`.

    Yields
    ------
    library_path : str
        The path of each library depending on `lib_fname`, including
        `lib_fname`, without duplicates.
    """
    if visited is None:
        visited = {lib_fname}
    elif lib_fname in visited:
        return
    else:
        visited.add(lib_fname)
    if not filt_func(lib_fname):
        logger.debug("Ignoring %s and its dependencies.", lib_fname)
        return
    yield lib_fname
    for dependency_fname, install_name in get_dependencies(
        lib_fname, executable_path=executable_path, filt_func=filt_func
    ):
        if dependency_fname is None:
            logger.error(
                "%s not found, requested by %s",
                install_name,
                lib_fname,
            )
            continue
        yield from walk_library(
            dependency_fname,
            filt_func=filt_func,
            visited=visited,
            executable_path=executable_path,
        )


def walk_directory(
    root_path: str,
    filt_func: Callable[[str], bool] = lambda filepath: True,
    executable_path: str | None = None,
) -> Iterator[str]:
    """Walk along dependencies starting with the libraries within `root_path`.

    Dependencies which can not be resolved will be logged and ignored.

    Parameters
    ----------
    root_path : str
        The root directory to search for libraries depending on other libraries.
    filt_func : None or callable, optional
        A callable which accepts filename as argument and returns True if we
        should inspect the file or False otherwise.
        Defaults to inspecting all files for library dependencies.
        If `filt_func` filters a library it will will not further analyze any
        of that library's dependencies.
    executable_path : None or str, optional
        If not None, an alternative path to use for resolving
        `@executable_path`.

    Yields
    ------
    library_path : str
        Iterates over the libraries in `root_path` and each of their
        dependencies without any duplicates.
    """
    visited_paths: set[str] = set()
    for dirpath, dirnames, basenames in os.walk(root_path):
        for base in basenames:
            depending_path = realpath(pjoin(dirpath, base))
            if depending_path in visited_paths:
                continue  # A library in root_path was a dependency of another.
            if not filt_func(depending_path):
                continue
            yield from walk_library(
                depending_path,
                filt_func=filt_func,
                visited=visited_paths,
                executable_path=executable_path,
            )


def _tree_libs_from_libraries(
    libraries: Iterable[str],
    *,
    lib_filt_func: Callable[[str], bool],
    copy_filt_func: Callable[[str], bool],
    executable_path: str | None = None,
    ignore_missing: bool = False,
) -> dict[str, dict[str, str]]:
    """Return an analysis of the dependencies of `libraries`.

    Parameters
    ----------
    libraries : iterable of str
        The paths to the libraries to find dependencies of.
    lib_filt_func : callable, keyword-only
        A callable which accepts filename as argument and returns True if we
        should inspect the file or False otherwise.
        If `filt_func` filters a library it will will not further analyze any
        of that library's dependencies.
    copy_filt_func : callable, keyword-only
        Called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
    executable_path : None or str, optional, keyword-only
        If not None, an alternative path to use for resolving
        `@executable_path`.
    ignore_missing : bool, default=False, optional, keyword-only
        Continue even if missing dependencies are detected.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (``libpath``,
        ``dependings_dict``).

        ``libpath`` is a canonical (``os.path.realpath``) filename of library,
        or library name starting with {'@loader_path'}.


        ``dependings_dict`` is a dict with (key, value) pairs of
        (``depending_libpath``, ``install_name``), where ``dependings_libpath``
        is the canonical (``os.path.realpath``) filename of the library
        depending on ``libpath``, and ``install_name`` is the "install_name" by
        which ``depending_libpath`` refers to ``libpath``.

    Raises
    ------
    DelocationError
        When any dependencies can not be located and ``ignore_missing`` is
        False.
    """
    lib_dict: dict[str, dict[str, str]] = {}
    missing_libs = False
    for library_path in libraries:
        for depending_path, install_name in get_dependencies(
            library_path,
            executable_path=executable_path,
            filt_func=lib_filt_func,
        ):
            if depending_path is None:
                missing_libs = True
                continue
            if not copy_filt_func(depending_path):
                continue
            lib_dict.setdefault(depending_path, {})
            lib_dict[depending_path][library_path] = install_name

    if missing_libs and not ignore_missing:
        # get_dependencies will already have logged details of missing
        # libraries.
        raise DelocationError("Could not find all dependencies.")

    return lib_dict


def tree_libs_from_directory(
    start_path: str,
    *,
    lib_filt_func: Callable[[str], bool] = _filter_system_libs,
    copy_filt_func: Callable[[str], bool] = lambda path: True,
    executable_path: str | None = None,
    ignore_missing: bool = False,
) -> dict[str, dict[str, str]]:
    """Return an analysis of the libraries in the directory of `start_path`.

    Parameters
    ----------
    start_path : iterable of str
        Root path of tree to search for libraries depending on other libraries.
    lib_filt_func : callable, optional, keyword-only
        A callable which accepts filename as argument and returns True if we
        should inspect the file or False otherwise.
        If `filt_func` filters a library it will will not further analyze any
        of that library's dependencies.
        Defaults to inspecting all files except for system libraries.
    copy_filt_func : callable, optional, keyword-only
        Called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
        Defaults to copying all detected dependencies.
    executable_path : None or str, optional, keyword-only
        If not None, an alternative path to use for resolving
        `@executable_path`.
    ignore_missing : bool, default=False, optional, keyword-only
        Continue even if missing dependencies are detected.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (``libpath``,
        ``dependings_dict``).

        ``libpath`` is a canonical (``os.path.realpath``) filename of library,
        or library name starting with {'@loader_path'}.


        ``dependings_dict`` is a dict with (key, value) pairs of
        (``depending_libpath``, ``install_name``), where ``dependings_libpath``
        is the canonical (``os.path.realpath``) filename of the library
        depending on ``libpath``, and ``install_name`` is the "install_name" by
        which ``depending_libpath`` refers to ``libpath``.

    Raises
    ------
    DelocationError
        When any dependencies can not be located and ``ignore_missing`` is
        False.
    """
    return _tree_libs_from_libraries(
        walk_directory(
            start_path, lib_filt_func, executable_path=executable_path
        ),
        lib_filt_func=lib_filt_func,
        copy_filt_func=copy_filt_func,
        ignore_missing=ignore_missing,
    )


def _allow_all(path: str) -> bool:
    """Return True for all files."""
    return True


@deprecated("tree_libs doesn't support @loader_path and has been deprecated")
def tree_libs(
    start_path: str,
    filt_func: Callable[[str], bool] | None = None,
) -> dict[str, dict[str, str]]:
    """Return analysis of library dependencies within `start_path`.

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

        ``libpath`` is a canonical (``os.path.realpath``) filename of library,
        or library name starting with {'@loader_path'}.


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

    .. deprecated:: 0.9
        This function does not support `@loader_path` and only returns the
        direct dependencies of the libraries in `start_path`.

        :func:`tree_libs_from_directory` should be used instead.
    """
    if filt_func is None:
        filt_func = _allow_all
    lib_dict: dict[str, dict[str, str]] = {}
    for dirpath, dirnames, basenames in os.walk(start_path):
        for base in basenames:
            depending_path = realpath(pjoin(dirpath, base))
            for dependency_path, install_name in get_dependencies(
                depending_path,
                filt_func=filt_func,
            ):
                if dependency_path is None:
                    # Mimic deprecated behavior.
                    # A lib_dict with unresolved paths is unsuitable for
                    # delocating, this is a missing dependency.
                    dependency_path = realpath(install_name)
                if install_name.startswith("@loader_path/"):
                    # Support for `@loader_path` would break existing callers.
                    logger.debug(
                        "Excluding %s because it has '@loader_path'.",
                        install_name,
                    )
                    continue
                lib_dict.setdefault(dependency_path, {})
                lib_dict[dependency_path][depending_path] = install_name
    return lib_dict


_default_paths_to_search = ("/usr/local/lib", "/usr/lib")


def resolve_dynamic_paths(
    lib_path: str | PathLike[str],
    rpaths: Iterable[str | PathLike[str]],
    loader_path: str | PathLike[str],
    executable_path: str | PathLike[str] | None = None,
) -> str:
    """Return `lib_path` with any special runtime linking names resolved.

    If `lib_path` has `@rpath` then returns the first `rpaths`/`lib_path`
    combination found.  If the library can't be found in `rpaths` then
    DependencyNotFound is raised.

    `@loader_path` and `@executable_path` are resolved with their respective
    parameters.

    Parameters
    ----------
    lib_path : str or PathLike
        The path to a library file, which may or may not be a relative path
        starting with `@rpath`, `@loader_path`, or `@executable_path`.
    rpaths : sequence of str or PathLike
        A sequence of search paths, usually gotten from a call to `get_rpaths`.
    loader_path : str or PathLike
        The path to be used for `@loader_path`.
        This should be the directory of the library which is loading `lib_path`.
    executable_path : None or str or PathLike, optional
        The path to be used for `@executable_path`.
        If None is given then the path of the Python executable will be used.

    Returns
    -------
    lib_path : str
        A str with the resolved libraries realpath.

    Raises
    ------
    DependencyNotFound
        When `lib_path` has `@rpath` in it but no library can be found on any
        of the provided `rpaths`.
    """
    lib_path = Path(lib_path)

    if executable_path is None:
        executable_path = Path(sys.executable).parent

    if lib_path.parts[0] not in (
        ("@rpath", "@loader_path", "@executable_path")
    ):
        return str(Path(lib_path).resolve())

    paths_to_search = []
    if lib_path.parts[0] == "@loader_path":
        paths_to_search = [loader_path]
    elif lib_path.parts[0] == "@executable_path":
        paths_to_search = [executable_path]
    elif lib_path.parts[0] == "@rpath":
        paths_to_search = list(rpaths)

    # these paths are searched by the macos loader in order if the
    # library is not in the previous paths.
    paths_to_search.extend(_default_paths_to_search)

    rel_path = Path(*lib_path.parts[1:])
    for prefix_path in paths_to_search:
        try:
            abs_path = Path(
                resolve_dynamic_paths(
                    Path(prefix_path, rel_path),
                    (),
                    loader_path,
                    executable_path,
                )
            ).resolve()
        except DependencyNotFound:
            continue
        if abs_path.exists():
            return str(abs_path)

    raise DependencyNotFound(lib_path)


@deprecated(
    "This function doesn't support @loader_path "
    "and was replaced by resolve_dynamic_paths"
)
def resolve_rpath(lib_path: str, rpaths: Iterable[str]) -> str:
    """Return `lib_path` with its `@rpath` resolved.

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

    .. deprecated:: 0.9
        This function does not support `@loader_path`.
        Use `resolve_dynamic_paths` instead.
    """
    if not lib_path.startswith("@rpath/"):
        return lib_path

    lib_rpath = lib_path.split("/", 1)[1]
    for rpath in (*rpaths, *_default_paths_to_search):
        rpath_lib = realpath(pjoin(rpath, lib_rpath))
        if os.path.exists(rpath_lib):
            return rpath_lib

    warnings.warn(
        "Couldn't find {} on paths:\n\t{}".format(
            lib_path,
            "\n\t".join(realpath(path) for path in rpaths),
        )
    )
    return lib_path


def search_environment_for_lib(lib_path: str | PathLike[str]) -> str:
    """Search common environment variables for `lib_path`.

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
    lib_path : str or PathLike
        Name of the library to search for

    Returns
    -------
    lib_path : str
        Real path of the first found location, if it can be found, or
        ``realpath(lib_path)`` if it cannot.
    """
    lib_path = Path(lib_path)
    potential_library_locations: list[Path] = [
        # 1. Search on DYLD_LIBRARY_PATH
        *_paths_from_var("DYLD_LIBRARY_PATH", lib_path.name),
        # 2. Search for realpath(lib_path)
        lib_path.resolve(),
        # 3. Search on DYLD_FALLBACK_LIBRARY_PATH
        *_paths_from_var("DYLD_FALLBACK_LIBRARY_PATH", lib_path.name),
    ]

    for location in potential_library_locations:
        if location.exists():
            # See GH#133 for why we return the realpath here if it can be found
            return str(location.resolve())
    return str(lib_path.resolve())


def get_prefix_stripper(strip_prefix: str) -> Callable[[str], str]:
    """Return function to strip `strip_prefix` prefix from string if present.

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

    def stripper(path: str) -> str:
        return path if not path.startswith(strip_prefix) else path[n:]

    return stripper


def get_rp_stripper(strip_path: str) -> Callable[[str], str]:
    """Return function to strip ``realpath`` of `strip_path` from string.

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


def stripped_lib_dict(
    lib_dict: dict[str, dict[str, str]], strip_prefix: str
) -> dict[str, dict[str, str]]:
    """Return `lib_dict` with `strip_prefix` removed from start of paths.

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


def wheel_libs(
    wheel_fname: str,
    filt_func: Callable[[str], bool] | None = None,
    *,
    ignore_missing: bool = False,
) -> dict[str, dict[str, str]]:
    """Return analysis of library dependencies with a Python wheel.

    Use this routine for a dump of the dependency tree.

    Parameters
    ----------
    wheel_fname : str
        Filename of wheel
    filt_func : None or callable, optional
        If None, inspect all non-system files for library dependencies.
        If callable, accepts filename as argument, returns True if we should
        inspect the file, False otherwise.
    ignore_missing : bool, default=False, optional, keyword-only
        Continue even if missing dependencies are detected.

    Returns
    -------
    lib_dict : dict
        dictionary with (key, value) pairs of (``libpath``,
        ``dependings_dict``).  ``libpath`` is library being depended on,
        relative to wheel root path if within wheel tree.  ``dependings_dict``
        is (key, value) of (``depending_lib_path``, ``install_name``).  Again,
        ``depending_lib_path`` is library relative to wheel root path, if
        within wheel tree.

    Raises
    ------
    DelocationError
        When dependencies can not be located and `ignore_missing` is False.
    """
    if filt_func is None:
        filt_func = _filter_system_libs
    with TemporaryDirectory() as tmpdir:
        zip2dir(wheel_fname, tmpdir)
        lib_dict = tree_libs_from_directory(
            tmpdir, lib_filt_func=filt_func, ignore_missing=ignore_missing
        )
    return stripped_lib_dict(lib_dict, realpath(tmpdir) + os.path.sep)


def _paths_from_var(
    varname: str, lib_basename: str | PathLike[str]
) -> Iterator[Path]:
    var = os.environ.get(varname)
    if var is None:
        return
    yield from (Path(path, lib_basename) for path in var.split(os.pathsep))

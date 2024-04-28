"""Routines to copy / relink library dependencies in trees and wheels."""

from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import stat
import warnings
from os.path import abspath, basename, dirname, exists, realpath, relpath
from os.path import join as pjoin
from pathlib import Path
from subprocess import PIPE, Popen
from typing import (
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Text,
    Tuple,
    Union,
)

from macholib.mach_o import (  # type: ignore[import-untyped]
    CPU_TYPE_NAMES,
    LC_BUILD_VERSION,
    LC_VERSION_MIN_MACOSX,
)
from macholib.MachO import MachO  # type: ignore[import-untyped]
from packaging.utils import parse_wheel_filename
from packaging.version import Version

from .libsana import (
    DelocationError,
    _allow_all,
    get_rp_stripper,
    stripped_lib_dict,
    tree_libs,
    tree_libs_from_directory,
)
from .pkginfo import read_pkg_info, write_pkg_info
from .tmpdirs import TemporaryDirectory
from .tools import (
    _is_macho_file,
    _remove_absolute_rpaths,
    dir2zip,
    find_package_dirs,
    get_archs,
    set_install_id,
    set_install_name,
    validate_signature,
    zip2dir,
)
from .wheeltools import InWheel, rewrite_record

logger = logging.getLogger(__name__)

# Prefix for install_name_id of copied libraries
DLC_PREFIX = "/DLC/"

_PLATFORM_REGEXP = re.compile(r"macosx_(\d+)_(\d+)_(\w+)")


def delocate_tree_libs(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
    lib_path: Text,
    root_path: Text,
    *,
    sanitize_rpaths: bool = False,
) -> Dict[Text, Dict[Text, Text]]:
    """Move needed libraries in `lib_dict` into `lib_path`.

    `lib_dict` has keys naming libraries required by the files in the
    corresponding value.  Call the keys, "required libs".  Call the values
    "requiring objects".

    Copy all the required libs to `lib_path`.  Fix up the rpaths and install
    names in the requiring objects to point to these new copies.

    Exception: required libs within the directory tree pointed to by
    `root_path` stay where they are, but we modify requiring objects to use
    relative paths to these libraries.

    Parameters
    ----------
    lib_dict : dict
        Dictionary with (key, value) pairs of (``depended_lib_path``,
        ``dependings_dict``) (see :func:`libsana.tree_libs`)
    lib_path : str
        Path in which to store copies of libs referred to in keys of
        `lib_dict`.  Assumed to exist
    root_path : str
        Root directory of tree analyzed in `lib_dict`.  Any required
        library within the subtrees of `root_path` does not get copied, but
        libraries linking to it have links adjusted to use relative path to
        this library.
    sanitize_rpaths : bool, default=False, keyword-only
        If True, absolute paths in rpaths of binaries are removed.

    Returns
    -------
    copied_libs : dict
        Filtered `lib_dict` dict containing only the (key, value) pairs from
        `lib_dict` where the keys are the libraries copied to `lib_path``.

    Raises
    ------
    DelocationError
        When a malformed `lib_dict` has unresolved paths, missing files, etc.
        When two dependencies would've been be copied to the same destination.
    """
    # Test for errors first to avoid getting half-way through changing the tree
    libraries_to_copy, libraries_to_delocate = _analyze_tree_libs(
        lib_dict, root_path
    )
    # Copy libraries and update lib_dict.
    lib_dict, copied_libraries = _copy_required_libs(
        lib_dict, lib_path, root_path, libraries_to_copy
    )
    # Update the install names of local and copied libaries.
    _update_install_names(
        lib_dict, root_path, libraries_to_delocate | copied_libraries
    )
    # Remove absolute rpaths
    if sanitize_rpaths:
        _sanitize_rpaths(lib_dict, libraries_to_delocate | copied_libraries)

    return libraries_to_copy


def _sanitize_rpaths(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
    files_to_delocate: Iterable[Text],
) -> None:
    """Sanitize the rpaths of libraries."""
    for required in files_to_delocate:
        # Set relative path for local library
        for requiring, orig_install_name in lib_dict[required].items():
            _remove_absolute_rpaths(requiring)


def _analyze_tree_libs(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
    root_path: Text,
) -> Tuple[Dict[Text, Dict[Text, Text]], Set[Text]]:
    """Verify then return which library files to copy and delocate.

    Returns
    -------
    needs_copying : dict
        The libraries outside of `root_path`.
        This is in the `lib_dict` format for use by `delocate_tree_libs`.
    needs_delocating : set of str
        The libraries inside of `root_path` which need to be delocated.
    """
    needs_delocating = set()  # Libraries which need install names updated.
    needs_copying = {}  # A report of which libraries were copied.
    copied_basenames = set()
    rp_root_path = realpath(root_path)
    for required, requirings in lib_dict.items():
        if required.startswith("@"):
            # @rpath, etc, at this point should never happen.
            raise DelocationError("%s was expected to be resolved." % required)
        r_ed_base = basename(required)
        if relpath(required, rp_root_path).startswith(".."):
            # Not local, plan to copy
            if r_ed_base in copied_basenames:
                raise DelocationError(
                    "Already planning to copy library with same basename as: "
                    + r_ed_base
                )
            if not exists(required):
                raise DelocationError(
                    'library "{0}" does not exist'.format(required)
                )
            # Copy requirings to preserve it since it will be modified later.
            needs_copying[required] = dict(requirings)
            copied_basenames.add(r_ed_base)
        else:  # Is local, plan to set relative loader_path
            needs_delocating.add(required)
    return needs_copying, needs_delocating


def _copy_required_libs(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
    lib_path: Text,
    root_path: Text,
    libraries_to_copy: Iterable[Text],
) -> Tuple[Dict[Text, Dict[Text, Text]], Set[Text]]:
    """Copy libraries outside of root_path to lib_path.

    Returns
    -------
    updated_lib_dict : dict
        A copy of `lib_dict` modified so that dependencies now point to
        the copied library destinations.
    needs_delocating : set of str
        A set of the destination files, these need to be delocated.
    """
    # Create a copy of lib_dict for this script to modify and return.
    out_lib_dict = _copy_lib_dict(lib_dict)
    del lib_dict
    needs_delocating = set()  # Set[Text]
    for old_path in libraries_to_copy:
        new_path = realpath(pjoin(lib_path, basename(old_path)))
        logger.info(
            "Copying library %s to %s", old_path, relpath(new_path, root_path)
        )
        shutil.copy(old_path, new_path)
        # Make copied file writeable if necessary.
        statinfo = os.stat(new_path)
        if not statinfo.st_mode & stat.S_IWRITE:
            os.chmod(new_path, statinfo.st_mode | stat.S_IWRITE)

        # Delocate this file now that it is stored locally.
        needs_delocating.add(new_path)
        # Update out_lib_dict with the new file paths.
        out_lib_dict[new_path] = out_lib_dict[old_path]
        del out_lib_dict[old_path]
        for required in out_lib_dict:
            if old_path not in out_lib_dict[required]:
                continue
            out_lib_dict[required][new_path] = out_lib_dict[required][old_path]
            del out_lib_dict[required][old_path]
    return out_lib_dict, needs_delocating


def _update_install_names(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
    root_path: Text,
    files_to_delocate: Iterable[Text],
) -> None:
    """Update the install names of libraries."""
    for required in files_to_delocate:
        # Set relative path for local library
        for requiring, orig_install_name in lib_dict[required].items():
            req_rel = relpath(required, dirname(requiring))
            new_install_name = "@loader_path/" + req_rel
            if orig_install_name == new_install_name:
                logger.info(
                    "NOT modifying install name in %s from %s, as the new name"
                    " would be the same.",
                    relpath(requiring, root_path),
                    orig_install_name,
                )
            else:
                logger.info(
                    "Modifying install name in %s from %s to %s",
                    relpath(requiring, root_path),
                    orig_install_name,
                    new_install_name,
                )
                set_install_name(requiring, orig_install_name, new_install_name)


def copy_recurse(
    lib_path: Text,
    copy_filt_func: Optional[Callable[[Text], bool]] = None,
    copied_libs: Optional[Dict[Text, Dict[Text, Text]]] = None,
) -> Dict[Text, Dict[Text, Text]]:
    """Analyze `lib_path` for library dependencies and copy libraries.

    `lib_path` is a directory containing libraries.  The libraries might
    themselves have dependencies.  This function analyzes the dependencies and
    copies library dependencies that match the filter `copy_filt_func`. It also
    adjusts the depending libraries to use the copy. It keeps iterating over
    `lib_path` until all matching dependencies (of dependencies of dependencies
    ...) have been copied.

    Parameters
    ----------
    lib_path : str
        Directory containing libraries
    copy_filt_func : None or callable, optional
        If None, copy any library that found libraries depend on.  If callable,
        called on each depended library name; copy where
        ``copy_filt_func(libname)`` is True, don't copy otherwise
    copied_libs : dict
        Dict with (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``) where ``copied_lib_path`` is the canonical path of
        a library that has been copied to `lib_path`, and ``dependings_dict``
        is a dictionary with (key, value) pairs of (``depending_lib_path``,
        ``install_name``).  ``depending_lib_path`` is the canonical path of the
        library depending on ``copied_lib_path``, ``install_name`` is the name
        that ``depending_lib_path`` uses to refer to ``copied_lib_path`` (in
        its install names).

    Returns
    -------
    copied_libs : dict
        Input `copied_libs` dict with any extra libraries and / or dependencies
        added.

    .. deprecated:: 0.9
        This function is obsolete.  :func:`delocate_path` handles recursive
        dependencies while also supporting `@loader_path`.
    """
    warnings.warn(
        "copy_recurse is obsolete and should no longer be called.",
        DeprecationWarning,
        stacklevel=2,
    )
    if copied_libs is None:
        copied_libs = {}
    else:
        copied_libs = dict(copied_libs)
    done = False
    while not done:
        in_len = len(copied_libs)
        _copy_required(lib_path, copy_filt_func, copied_libs)
        done = len(copied_libs) == in_len
    return copied_libs


def _copy_required(
    lib_path: Text,
    copy_filt_func: Optional[Callable[[Text], bool]],
    copied_libs: Dict[Text, Dict[Text, Text]],
) -> None:
    """Copy libraries required for files in `lib_path` to `copied_libs`.

    Augment `copied_libs` dictionary with any newly copied libraries, modifying
    `copied_libs` in-place - see Notes.

    This is one pass of ``copy_recurse``

    Parameters
    ----------
    lib_path : str
        Directory containing libraries
    copy_filt_func : None or callable, optional
        If None, copy any library that found libraries depend on.  If callable,
        called on each library name; copy where ``copy_filt_func(libname)`` is
        True, don't copy otherwise
    copied_libs : dict
        See :func:`copy_recurse` for definition.

    Notes
    -----
    If we need to copy another library, add that (``depended_lib_path``,
    ``dependings_dict``) to `copied_libs`.  ``dependings_dict`` has (key,
    value) pairs of (``depending_lib_path``, ``install_name``).
    ``depending_lib_path`` will be the original (canonical) library name, not
    the copy in ``lib_path``.

    Sometimes we copy a library, that further depends on a library we have
    already copied. In this case update ``copied_libs[depended_lib]`` with the
    extra dependency (as well as fixing up the install names for the depending
    library).

    For example, imagine we've start with a lib path like this::

        my_lib_path/
            libA.dylib
            libB.dylib

    Our input `copied_libs` has keys ``/sys/libA.dylib``, ``/sys/libB.lib``
    telling us we previously copied those guys from the ``/sys`` folder.

    On a first pass, we discover that ``libA.dylib`` depends on
    ``/sys/libC.dylib``, so we copy that.

    On a second pass, we discover now that ``libC.dylib`` also depends on
    ``/sys/libB.dylib``.  `copied_libs` tells us that we already have a copy of
    ``/sys/libB.dylib``, so we fix our copy of `libC.dylib`` to point to
    ``my_lib_path/libB.dylib`` and add ``/sys/libC.dylib`` as a
    ``dependings_dict`` entry for ``copied_libs['/sys/libB.dylib']``

    .. deprecated:: 0.9
        This function is obsolete, and is only used by :func:`copy_recurse`.
    """
    # Paths will be prepended with `lib_path`
    lib_dict = tree_libs(lib_path)
    # Map library paths after copy ('copied') to path before copy ('orig')
    rp_lp = realpath(lib_path)
    copied2orig = dict((pjoin(rp_lp, basename(c)), c) for c in copied_libs)
    for required, requirings in lib_dict.items():
        if copy_filt_func is not None and not copy_filt_func(required):
            continue
        if required.startswith("@"):
            # May have been processed by us, or have some rpath, loader_path of
            # its own. Either way, leave alone
            continue
        # Requiring names may well be the copies in lib_path.  Replace the copy
        # names with the original names for entry into `copied_libs`
        procd_requirings = {}
        # Set requiring lib install names to point to local copy
        for requiring, orig_install_name in requirings.items():
            set_install_name(
                requiring,
                orig_install_name,
                "@loader_path/" + basename(required),
            )
            # Make processed version of ``dependings_dict``
            mapped_requiring = copied2orig.get(requiring, requiring)
            procd_requirings[mapped_requiring] = orig_install_name
        if required in copied_libs:
            # Have copied this already, add any new requirings
            copied_libs[required].update(procd_requirings)
            continue
        # Haven't see this one before, add entry to copied_libs
        out_path = pjoin(lib_path, basename(required))
        if exists(out_path):
            raise DelocationError(out_path + " already exists")
        shutil.copy(required, lib_path)
        copied2orig[out_path] = required
        copied_libs[required] = procd_requirings


def _dylibs_only(filename: str) -> bool:
    return filename.endswith(".so") or filename.endswith(".dylib")


def filter_system_libs(libname: str) -> bool:
    """Return False for system libraries."""
    return not (libname.startswith("/usr/lib") or libname.startswith("/System"))


def _delocate_filter_function(
    path: str,
    *,
    lib_filt_func: Callable[[str], bool],
    copy_filt_func: Callable[[str], bool],
) -> bool:
    """Combine the library inspection and copy filters into one function.

    So that libraries which won't be copied will not be followed.
    """
    return lib_filt_func(path) and copy_filt_func(path)


def delocate_path(
    tree_path: Text,
    lib_path: Text,
    lib_filt_func: Optional[Union[str, Callable[[Text], bool]]] = None,
    copy_filt_func: Optional[Callable[[Text], bool]] = filter_system_libs,
    executable_path: Optional[Text] = None,
    ignore_missing: bool = False,
    *,
    sanitize_rpaths: bool = False,
) -> Dict[Text, Dict[Text, Text]]:
    """Copy required libraries for files in `tree_path` into `lib_path`.

    Parameters
    ----------
    tree_path : str
        Root path of tree to search for required libraries
    lib_path : str
        Directory into which we copy required libraries
    lib_filt_func : None or str or callable, optional
        If None, inspect all files for dependencies on dynamic libraries. If
        callable, accepts filename as argument, returns True if we should
        inspect the file, False otherwise. If str == "dylibs-only" then inspect
        only files with known dynamic library extensions (``.dylib``, ``.so``).
    copy_filt_func : None or callable, optional
        If callable, called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
        Default is callable rejecting only libraries beginning with
        ``/usr/lib`` or ``/System``.  None means copy all libraries. This will
        usually end up copying large parts of the system run-time.
        Libraries which won't be copied will not be inspected for dependencies.
    executable_path : None or str, optional
        If not None, an alternative path to use for resolving
        `@executable_path`.
    ignore_missing : bool, default=False
        Continue even if missing dependencies are detected.
    sanitize_rpaths : bool, default=False, keyword-only
        If True, absolute paths in rpaths of binaries are removed.

    Returns
    -------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that was copied into `lib_sdir` of the wheel packages, and
        ``dependings_dict`` is a dictionary with key, value pairs where the key
        is a file in the path depending on ``copied_lib_path``, and the value
        is the ``install_name`` of ``copied_lib_path`` in the depending
        library.

    Raises
    ------
    DelocationError
        When any dependencies can not be located.
    """
    if lib_filt_func == "dylibs-only":
        lib_filt_func = _dylibs_only
    elif isinstance(lib_filt_func, str):
        raise TypeError('lib_filt_func string can only be "dylibs-only"')
    if lib_filt_func is None:
        lib_filt_func = _allow_all
    if copy_filt_func is None:
        copy_filt_func = _allow_all
    if not exists(lib_path):
        os.makedirs(lib_path)
    # Do not inspect dependencies of libraries that will not be copied.
    filt_func = functools.partial(
        _delocate_filter_function,
        lib_filt_func=lib_filt_func,
        copy_filt_func=copy_filt_func,
    )

    lib_dict = tree_libs_from_directory(
        tree_path,
        lib_filt_func=filt_func,
        copy_filt_func=filt_func,
        executable_path=executable_path,
        ignore_missing=ignore_missing,
    )

    return delocate_tree_libs(
        lib_dict, lib_path, tree_path, sanitize_rpaths=sanitize_rpaths
    )


def _copy_lib_dict(
    lib_dict: Mapping[Text, Mapping[Text, Text]],
) -> Dict[Text, Dict[Text, Text]]:
    """Return a copy of lib_dict."""
    return {  # Convert nested Mapping types into nested Dict types.
        required: dict(requiring) for required, requiring in lib_dict.items()
    }


def _decide_dylib_bundle_directory(
    wheel_dir: str, package_name: str, lib_sdir: str = ".dylibs"
) -> str:
    """Return a relative directory which should be used to store dylib files.

    Parameters
    ----------
    wheel_dir : str
        The directory of an unpacked wheel to analyse.
    package_name : str
        The name of the package.
    lib_sdir : str, optional
        Default value for lib sub-directory passed in via
        :func:`delocate_wheel`.
        Ignored if wheel has no package directories.

    Returns
    -------
    dylibs_dir : str
        A path to within `wheel_dir` where any library files should be put.
    """
    package_dirs = find_package_dirs(wheel_dir)
    for directory in package_dirs:
        if Path(directory).name == package_name:
            # Prefer using the directory with the same name as the package.
            return pjoin(directory, lib_sdir)
    if package_dirs:
        # Otherwise, store dylib files in the first package alphabetically.
        return pjoin(min(package_dirs), lib_sdir)
    # Otherwise, use an auditwheel-style top-level name.
    return pjoin(wheel_dir, f"{package_name}.dylibs")


def _make_install_name_ids_unique(
    libraries: Iterable[str], install_id_prefix: str
) -> None:
    """Replace each library's install name id with a unique id.

    This is to change install ids to be unique within Python space.

    Parameters
    ----------
    libraries : iterable of str
        The libraries to be modified.
        These files are assumed to be in the same directory.
    install_id_prefix : str
        A unique path to use as a prefix for the install name ids.
        This must be a Unix absolute path.

    Examples
    --------
    >>> _make_install_name_ids_unique((), "/")
    >>> _make_install_name_ids_unique((), "")
    Traceback (most recent call last):
        ...
    ValueError: install_id_prefix should start with '/', got ''
    """
    if not install_id_prefix.startswith("/"):
        raise ValueError(
            "install_id_prefix should start with '/',"
            f" got {install_id_prefix!r}"
        )
    if not install_id_prefix.endswith("/"):
        install_id_prefix += "/"
    for lib in libraries:
        set_install_id(lib, install_id_prefix + basename(lib))
        validate_signature(lib)


def _get_macos_min_version(dylib_path: Path) -> Iterator[tuple[str, Version]]:
    """Get the minimum macOS version from a dylib file.

    Parameters
    ----------
    dylib_path : Path
        The path to the dylib file.

    Yields
    ------
    str
        The CPU type.
    Version
        The minimum macOS version.
    """
    if not _is_macho_file(dylib_path):
        return
    for header in MachO(dylib_path).headers:
        for cmd in header.commands:
            if cmd[0].cmd == LC_BUILD_VERSION:
                version = cmd[1].minos
            elif cmd[0].cmd == LC_VERSION_MIN_MACOSX:
                version = cmd[1].version
            else:
                continue
            yield (
                CPU_TYPE_NAMES.get(header.header.cputype, "unknown"),
                Version(f"{version >> 16 & 0xFF}.{version >> 8 & 0xFF}"),
            )
            break


def _get_archs_and_version_from_wheel_name(
    wheel_name: str,
) -> dict[str, Version]:
    """Get the architecture and minimum macOS version from the wheel name.

    Parameters
    ----------
    wheel_name : str
        The name of the wheel.

    Returns
    -------
    Dict[str, Version]
        A dictionary containing the architecture and minimum macOS version
        for each architecture in the wheel name.
    """
    platform_tag_set = parse_wheel_filename(wheel_name)[-1]
    platform_requirements = {}
    for platform_tag in platform_tag_set:
        match = _PLATFORM_REGEXP.match(platform_tag.platform)
        if match is None:
            raise ValueError(f"Invalid platform tag: {platform_tag.platform}")
        major, minor, arch = match.groups()
        platform_requirements[arch] = Version(f"{major}.{minor}")
    # If we have a wheel name with arm64 and x86_64 we have to convert that to
    # universal2
    if platform_requirements.keys() == {"arm64", "x86_64"}:
        version = platform_requirements["arm64"]
        if version == Version("11.0"):
            version = platform_requirements["x86_64"]
        platform_requirements = {"universal2": version}

    return platform_requirements


def _get_problematic_libs(
    required_version: Optional[Version],
    version_lib_dict: Dict[Version, List[Path]],
    arch: str,
) -> set[tuple[Path, Version]]:
    """Find libraries which require a more modern macOS version.

    Parameters
    ----------
    required_version : Version or None
        The expected minimum macOS version.
        If None, return an empty set.
    version_lib_dict : Dict[Version, List[Path]]
        A dictionary containing mapping from minimum macOS version to libraries
        that require that version.
    arch : str
        The architecture of the libraries. For proper handle arm64 case

    Returns
    -------
    set[tuple[Path, Version]]
        A set of libraries that require a more modern macOS version than the
        provided one.
    """
    if required_version is None:
        return set()
    if arch == "arm64" and required_version < Version("11.0"):
        # All arm64 libraries require macOS at least 11.0,
        # So even if user provide lower deployment target,
        # for example, by setting environment variable
        # MACOSX_DEPLOYMENT_TARGET=10.15
        # the binaries still will be compatible with 11.0+ only.
        # So there is no need to check for compatible with older macOS versions
        required_version = Version("11.0")
    bad_libraries: set[tuple[Path, Version]] = set()
    for library_version, libraries in version_lib_dict.items():
        if library_version > required_version:
            bad_libraries.update((path, library_version) for path in libraries)
    return bad_libraries


def _calculate_minimum_wheel_name(
    wheel_name: str,
    wheel_dir: Path,
    require_target_macos_version: Optional[Version],
) -> tuple[str, set[tuple[Path, Version]]]:
    """Return a wheel name with an updated platform tag.

    Based on the architecture of the libraries in the wheel and actual platform
    tag.

    Parameters
    ----------
    wheel_name : str
        The name of the wheel.
    wheel_dir : Path
        The directory of the unpacked wheel.
    require_target_macos_version : Version or None
        The target macOS version that the wheel should be compatible with.

    Returns
    -------
    str
        The updated wheel name.
    set[tuple[Path, Version]]
        A set of libraries that require a more modern macOS version than the
        provided one.
    """
    # get platform tag from wheel name using packaging
    if wheel_name.endswith("any.whl"):
        # universal wheel, no need to update the platform tag
        return wheel_name, set()
    arch_version = _get_archs_and_version_from_wheel_name(wheel_name)
    # get the architecture and minimum macOS version from the libraries
    # in the wheel
    version_info_dict: Dict[str, Dict[Version, List[Path]]] = {}

    for lib in wheel_dir.glob("**/*"):
        for arch, version in _get_macos_min_version(lib):
            version_info_dict.setdefault(arch.lower(), {}).setdefault(
                version, []
            ).append(lib)
    version_dkt = {
        arch: max(version) for arch, version in version_info_dict.items()
    }

    problematic_libs: set[tuple[Path, Version]] = set()

    try:
        for arch, version in list(arch_version.items()):
            if arch == "universal2":
                if version_dkt["arm64"] == Version("11.0"):
                    arch_version["universal2"] = max(
                        version, version_dkt["x86_64"]
                    )
                else:
                    arch_version["universal2"] = max(
                        version, version_dkt["arm64"], version_dkt["x86_64"]
                    )
                    problematic_libs.update(
                        _get_problematic_libs(
                            require_target_macos_version,
                            version_info_dict["arm64"],
                            "arm64",
                        )
                    )
                problematic_libs.update(
                    _get_problematic_libs(
                        require_target_macos_version,
                        version_info_dict["x86_64"],
                        "x86_64",
                    )
                )
            elif arch == "universal":
                arch_version["universal"] = max(
                    version, version_dkt["i386"], version_dkt["x86_64"]
                )
                problematic_libs.update(
                    _get_problematic_libs(
                        require_target_macos_version,
                        version_info_dict["i386"],
                        "i386",
                    ),
                    _get_problematic_libs(
                        require_target_macos_version,
                        version_info_dict["x86_64"],
                        "x86_64",
                    ),
                )
            else:
                arch_version[arch] = max(version, version_dkt[arch])
                problematic_libs.update(
                    _get_problematic_libs(
                        require_target_macos_version,
                        version_info_dict[arch],
                        arch,
                    )
                )
    except KeyError as e:
        raise DelocationError(
            f"Failed to find any binary with the required architecture: {e}"
        ) from e
    prefix = wheel_name.rsplit("-", 1)[0]
    platform_tag = ".".join(
        f"macosx_{version.major}_{version.minor}_{arch}"
        for arch, version in arch_version.items()
    )
    return f"{prefix}-{platform_tag}.whl", problematic_libs


def _check_and_update_wheel_name(
    wheel_path: Path,
    wheel_dir: Path,
    require_target_macos_version: Optional[Version],
) -> Path:
    """Determine the minimum platform tag and update the wheel name if needed.

    Based on current wheel name and binary files in the wheel.

    Parameters
    ----------
    wheel_path : Path
        The path to the wheel.
    wheel_dir : Path
        The directory of the unpacked wheel.
    require_target_macos_version : Version or None
        The target macOS version that the wheel should be compatible with.
        If provided and the wheel does not satisfy the target MacOS version,
        raise an error.
    """
    wheel_name = os.path.basename(wheel_path)

    new_name, problematic_files = _calculate_minimum_wheel_name(
        wheel_name, Path(wheel_dir), require_target_macos_version
    )
    if problematic_files:
        problematic_files_str = "\n".join(
            f"{lib_path} has a minimum target of {lib_macos_version}"
            for lib_path, lib_macos_version in problematic_files
        )
        min_valid_version = max(
            lib_macos_version for _, lib_macos_version in problematic_files
        )
        raise DelocationError(
            "Library dependencies do not satisfy target MacOS"
            f" version {require_target_macos_version}:\n"
            f"{problematic_files_str}"
            f"\nUse '--require-target-macos-version {min_valid_version}'"
            " or set the environment variable"
            f" 'MACOSX_DEPLOYMENT_TARGET={min_valid_version}'"
            " to update minimum supported macOS for this wheel."
        )
    if new_name != wheel_name:
        wheel_path = wheel_path.parent / new_name
    return wheel_path


def _update_wheelfile(wheel_dir: Path, wheel_name: str) -> None:
    """
    Update the WHEEL file in the wheel directory with the new platform tag.

    Parameters
    ----------
    wheel_dir : Path
        The directory of the unpacked wheel.
    wheel_name : str
        The name of the wheel.
        Used for determining the new platform tag.
    """
    platform_tag_set = parse_wheel_filename(wheel_name)[-1]
    (file_path,) = wheel_dir.glob("*.dist-info/WHEEL")
    info = read_pkg_info(file_path)
    del info["Tag"]
    for tag in platform_tag_set:
        info.add_header("Tag", str(tag))
    write_pkg_info(file_path, info)


def delocate_wheel(
    in_wheel: str,
    out_wheel: Optional[str] = None,
    lib_sdir: str = ".dylibs",
    lib_filt_func: Union[None, str, Callable[[str], bool]] = None,
    copy_filt_func: Optional[Callable[[str], bool]] = filter_system_libs,
    require_archs: Union[None, str, Iterable[str]] = None,
    check_verbose: Optional[bool] = None,
    *,
    executable_path: Optional[str] = None,
    ignore_missing: bool = False,
    sanitize_rpaths: bool = False,
    require_target_macos_version: Optional[Version] = None,
) -> Dict[str, Dict[str, str]]:
    """Update wheel by copying required libraries to `lib_sdir` in wheel.

    Create `lib_sdir` in wheel tree only if we are copying one or more
    libraries.

    If `out_wheel` is None (the default), overwrite the wheel `in_wheel`
    in-place.

    Parameters
    ----------
    in_wheel : str
        Filename of wheel to process
    out_wheel : None or str
        Filename of processed wheel to write.  If None, overwrite `in_wheel`
    lib_sdir : str, optional
        Subdirectory name in wheel package directory (or directories) to store
        needed libraries.
        Ignored if the wheel has no package directories, and only contains
        stand-alone modules.
    lib_filt_func : None or str or callable, optional
        If None, inspect all files for dependencies on dynamic libraries. If
        callable, accepts filename as argument, returns True if we should
        inspect the file, False otherwise. If str == "dylibs-only" then inspect
        only files with known dynamic library extensions (``.dylib``, ``.so``).
    copy_filt_func : None or callable, optional
        If callable, called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
        Default is callable rejecting only libraries beginning with
        ``/usr/lib`` or ``/System``.  None means copy all libraries. This will
        usually end up copying large parts of the system run-time.
    require_archs : None or str or sequence, optional
        If None, do no checks of architectures in libraries.  If sequence,
        sequence of architectures (output from ``lipo -info``) that every
        library in the wheels should have (e.g. ``['x86_64, 'i386']``). An
        empty sequence results in checks that depended libraries have the same
        archs as depending libraries.  If string, either "intel" (corresponds
        to sequence ``['x86_64, 'i386']``) or name of required architecture
        (e.g "i386" or "x86_64").
    check_verbose : bool, optional
        This flag is deprecated, and has no effect.
    executable_path : None or str, optional, keyword-only
        An alternative path to use for resolving `@executable_path`.
    ignore_missing : bool, default=False, keyword-only
        Continue even if missing dependencies are detected.
    sanitize_rpaths : bool, default=False, keyword-only
        If True, absolute paths in rpaths of binaries are removed.
    require_target_macos_version : None or Version, optional, keyword-only
        If provided, the minimum macOS version that the wheel should support.

    Returns
    -------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that was copied into `lib_sdir` of the wheel packages, and
        ``dependings_dict`` is a dictionary with key, value pairs where the key
        is a path in the wheel depending on ``copied_lib_path``, and the value
        is the ``install_name`` of ``copied_lib_path`` in the depending
        library. The filenames in the keys are relative to the wheel root path.
    """
    if check_verbose is not None:
        warnings.warn(
            "The check_verbose flag is deprecated and shouldn't be provided,"
            " all subsequent parameters should be changed over to keywords.",
            DeprecationWarning,
            stacklevel=2,
        )
    in_wheel = abspath(in_wheel)
    if out_wheel is None:
        out_wheel = in_wheel
    else:
        out_wheel = abspath(out_wheel)
    in_place = in_wheel == out_wheel
    remove_old = in_place
    with TemporaryDirectory() as tmpdir:
        wheel_dir = realpath(pjoin(tmpdir, "wheel"))
        zip2dir(in_wheel, wheel_dir)
        # Assume the package name from the wheel filename.
        package_name = basename(in_wheel).split("-")[0]
        lib_sdir = _decide_dylib_bundle_directory(
            wheel_dir, package_name, lib_sdir
        )
        lib_path = pjoin(wheel_dir, lib_sdir)
        lib_path_exists_before_delocate = exists(lib_path)
        copied_libs = delocate_path(
            wheel_dir,
            lib_path,
            lib_filt_func,
            copy_filt_func,
            executable_path=executable_path,
            ignore_missing=ignore_missing,
            sanitize_rpaths=sanitize_rpaths,
        )
        if copied_libs and lib_path_exists_before_delocate:
            raise DelocationError(
                "f{lib_path} already exists in wheel but need to copy "
                + "; ".join(copied_libs)
            )
        if len(os.listdir(lib_path)) == 0:
            shutil.rmtree(lib_path)
        # Check architectures
        if require_archs is not None:
            bads = check_archs(copied_libs, require_archs)
            if bads:
                raise DelocationError(
                    "Some missing architectures in wheel"
                    f"\n{bads_report(bads, pjoin(tmpdir, 'wheel'))}"
                )
        libraries_in_lib_path = [
            pjoin(lib_path, basename(lib)) for lib in copied_libs
        ]
        _make_install_name_ids_unique(
            libraries=libraries_in_lib_path,
            install_id_prefix=DLC_PREFIX + relpath(lib_sdir, wheel_dir),
        )
        rewrite_record(wheel_dir)
        out_wheel_ = Path(out_wheel)
        out_wheel_fixed = _check_and_update_wheel_name(
            out_wheel_, Path(wheel_dir), require_target_macos_version
        )
        if out_wheel_fixed != out_wheel_:
            out_wheel_ = out_wheel_fixed
            in_place = False
            _update_wheelfile(Path(wheel_dir), out_wheel_.name)
        if len(copied_libs) or not in_place:
            if remove_old:
                os.remove(in_wheel)
            dir2zip(wheel_dir, out_wheel_)
    return stripped_lib_dict(copied_libs, wheel_dir + os.path.sep)


def patch_wheel(
    in_wheel: Text, patch_fname: Text, out_wheel: Optional[Text] = None
) -> None:
    """Apply ``-p1`` style patch in `patch_fname` to contents of `in_wheel`.

    If `out_wheel` is None (the default), overwrite the wheel `in_wheel`
    in-place.

    Parameters
    ----------
    in_wheel : str
        Filename of wheel to process
    patch_fname : str
        Filename of patch file.  Will be applied with ``patch -p1 <
        patch_fname``
    out_wheel : None or str
        Filename of patched wheel to write.  If None, overwrite `in_wheel`
    """
    in_wheel = abspath(in_wheel)
    patch_fname = abspath(patch_fname)
    if out_wheel is None:
        out_wheel = in_wheel
    else:
        out_wheel = abspath(out_wheel)
    if not exists(patch_fname):
        raise ValueError("patch file {0} does not exist".format(patch_fname))
    with InWheel(in_wheel, out_wheel):
        with open(patch_fname, "rb") as fobj:
            patch_proc = Popen(
                ["patch", "-p1"], stdin=fobj, stdout=PIPE, stderr=PIPE
            )
            stdout, stderr = patch_proc.communicate()
            if patch_proc.returncode != 0:
                raise RuntimeError(
                    "Patch failed with stdout:\n" + stdout.decode("latin1")
                )


_ARCH_LOOKUP = {"intel": ["i386", "x86_64"], "universal2": ["x86_64", "arm64"]}


def check_archs(
    copied_libs: Mapping[Text, Mapping[Text, Text]],
    require_archs: Union[Text, Iterable[Text]] = (),
    stop_fast: bool = False,
) -> Set[
    Union[Tuple[Text, FrozenSet[Text]], Tuple[Text, Text, FrozenSet[Text]]]
]:
    """Check compatibility of archs in `copied_libs` dict.

    Parameters
    ----------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that has been copied during delocation, and ``dependings_dict`` is a
        dictionary with key, value pairs where the key is a path in the target
        being delocated (a wheel or path) depending on ``copied_lib_path``, and
        the value is the ``install_name`` of ``copied_lib_path`` in the
        depending library.
    require_archs : str or sequence, optional
        Architectures we require to be present in all library files in wheel.
        If an empty sequence, just check that depended libraries do have the
        architectures of the depending libraries, with no constraints on what
        these architectures are. If a sequence, then a set of required
        architectures e.g. ``['i386', 'x86_64']`` to specify dual Intel
        architectures.  If a string, then a standard architecture name as
        returned by ``lipo -info``, or the string "intel", corresponding to the
        sequence ``['i386', 'x86_64']``, or the string "universal2",
        corresponding to ``['x86_64', 'arm64']``.
    stop_fast : bool, optional
        Whether to give up collecting errors after the first

    Returns
    -------
    bads : set
        set of length 2 or 3 tuples. A length 2 tuple is of form
        ``(depending_lib, missing_archs)`` meaning that an arch in
        `require_archs` was missing from ``depending_lib``.  A length 3 tuple
        is of form ``(depended_lib, depending_lib, missing_archs)`` where
        ``depended_lib`` is the filename of the library depended on,
        ``depending_lib`` is the library depending on ``depending_lib`` and
        ``missing_archs`` is a set of missing architecture strings giving
        architectures present in ``depending_lib`` and missing in
        ``depended_lib``.  An empty set means all architectures were present as
        required.
    """
    if isinstance(require_archs, str):
        require_archs = _ARCH_LOOKUP.get(require_archs, [require_archs])
    require_archs_set = frozenset(require_archs)
    bads: List[
        Union[Tuple[Text, FrozenSet[Text]], Tuple[Text, Text, FrozenSet[Text]]]
    ] = []
    for depended_lib, dep_dict in copied_libs.items():
        depended_archs = get_archs(depended_lib)
        for depending_lib, install_name in dep_dict.items():
            depending_archs = get_archs(depending_lib)
            all_required = depending_archs | require_archs_set
            all_missing = all_required.difference(depended_archs)
            if len(all_missing) == 0:
                continue
            required_missing = require_archs_set.difference(depended_archs)
            if len(required_missing):
                bads.append((depending_lib, required_missing))
            else:
                bads.append((depended_lib, depending_lib, all_missing))
            if stop_fast:
                return set(bads)
    return set(bads)


def bads_report(bads, path_prefix=None):
    """Return a nice report of bad architectures in `bads`.

    Parameters
    ----------
    bads : set
        set of length 2 or 3 tuples. A length 2 tuple is of form
        ``(depending_lib, missing_archs)`` meaning that an arch in
        `require_archs` was missing from ``depending_lib``.  A length 3 tuple
        is of form ``(depended_lib, depending_lib, missing_archs)`` where
        ``depended_lib`` is the filename of the library depended on,
        ``depending_lib`` is the library depending on ``depending_lib`` and
        ``missing_archs`` is a set of missing architecture strings giving
        architectures present in ``depending_lib`` and missing in
        ``depended_lib``.  An empty set means all architectures were present as
        required.
    path_prefix : None or str, optional
        Path prefix to strip from ``depended_lib`` and ``depending_lib``. None
        means do not strip anything.

    Returns
    -------
    report : str
        A nice report for printing
    """
    path_processor = (
        (lambda x: x) if path_prefix is None else get_rp_stripper(path_prefix)
    )
    reports = []
    for result in bads:
        if len(result) == 3:
            depended_lib, depending_lib, missing_archs = result
            reports.append(
                "{0} needs {1} {2} missing from {3}".format(
                    path_processor(depending_lib),
                    "archs" if len(missing_archs) > 1 else "arch",
                    ", ".join(sorted(missing_archs)),
                    path_processor(depended_lib),
                )
            )
        elif len(result) == 2:
            depending_lib, missing_archs = result
            reports.append(
                "Required {0} {1} missing from {2}".format(
                    "archs" if len(missing_archs) > 1 else "arch",
                    ", ".join(sorted(missing_archs)),
                    path_processor(depending_lib),
                )
            )
        else:
            raise ValueError("Report tuple should be length 2 or 3")
    return "\n".join(sorted(reports))

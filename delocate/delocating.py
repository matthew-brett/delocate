"""Routines to copy / relink library dependencies in trees and wheels."""

from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import stat
import struct
import warnings
from collections.abc import Iterable, Iterator, Mapping
from os.path import abspath, basename, dirname, exists, realpath, relpath
from os.path import join as pjoin
from pathlib import Path
from subprocess import PIPE, Popen
from typing import (
    Callable,
    Final,
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
    get_rp_stripper,
    stripped_lib_dict,
    tree_libs_from_directory,
)
from .pkginfo import read_pkg_info, write_pkg_info
from .tmpdirs import TemporaryDirectory
from .tools import (
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

try:
    from delocate._version import __version__
except ImportError:  # pragma: no cover
    __version__ = ""

logger = logging.getLogger(__name__)

# Prefix for install_name_id of copied libraries
DLC_PREFIX = "/DLC/"

_PLATFORM_REGEXP = re.compile(r"macosx_(\d+)_(\d+)_(\w+)")


def delocate_tree_libs(
    lib_dict: Mapping[str, Mapping[str, str]],
    lib_path: str,
    root_path: str,
    *,
    sanitize_rpaths: bool = False,
) -> dict[str, dict[str, str]]:
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
    lib_dict: Mapping[str, Mapping[str, str]],
    files_to_delocate: Iterable[str],
) -> None:
    """Sanitize the rpaths of libraries."""
    for required in files_to_delocate:
        # Set relative path for local library
        for requiring, orig_install_name in lib_dict[required].items():
            _remove_absolute_rpaths(requiring)


def _analyze_tree_libs(
    lib_dict: Mapping[str, Mapping[str, str]],
    root_path: str,
) -> tuple[dict[str, dict[str, str]], set[str]]:
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
            raise DelocationError(f"{required} was expected to be resolved.")
        r_ed_base = basename(required)
        if relpath(required, rp_root_path).startswith(".."):
            # Not local, plan to copy
            if r_ed_base in copied_basenames:
                raise DelocationError(
                    "Already planning to copy library with same basename as: "
                    + r_ed_base
                )
            if not exists(required):
                raise DelocationError(f'library "{required}" does not exist')
            # Copy requirings to preserve it since it will be modified later.
            needs_copying[required] = dict(requirings)
            copied_basenames.add(r_ed_base)
        else:  # Is local, plan to set relative loader_path
            needs_delocating.add(required)
    return needs_copying, needs_delocating


def _copy_required_libs(
    lib_dict: Mapping[str, Mapping[str, str]],
    lib_path: str,
    root_path: str,
    libraries_to_copy: Iterable[str],
) -> tuple[dict[str, dict[str, str]], set[str]]:
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
    lib_dict: Mapping[str, Mapping[str, str]],
    root_path: str,
    files_to_delocate: Iterable[str],
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


def _allow_all(path: str) -> bool:
    """Return True for all files."""
    return True


def delocate_path(
    tree_path: str,
    lib_path: str,
    lib_filt_func: str | Callable[[str], bool] | None = None,
    copy_filt_func: Callable[[str], bool] | None = filter_system_libs,
    executable_path: str | None = None,
    ignore_missing: bool = False,
    *,
    sanitize_rpaths: bool = False,
) -> dict[str, dict[str, str]]:
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
    lib_dict: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
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
        If wheel has no package directories, used as a suffix.

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
    return pjoin(wheel_dir, f"{package_name}{lib_sdir}")


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


def _get_macos_min_version(
    dylib_path: str | os.PathLike[str],
) -> Iterator[tuple[str, Version]]:
    """Get the minimum macOS version from a dylib file.

    Parameters
    ----------
    dylib_path : str or PathLike
        The path to the dylib file.

    Yields
    ------
    str
        The CPU type.
    Version
        The minimum macOS version.
    """
    try:
        macho = MachO(dylib_path)
    except struct.error:  # Parse error duing macholib's parsing
        return  # Not a recognised Mach-O object file
    except ValueError as exc:  # Raised by macholib for parse errors
        if str(exc.args[0]).startswith(
            ("Unknown fat header magic", "Unknown Mach-O header")
        ):
            return  # Not a recognised Mach-O object file
        raise  # pragma: no cover  # Unexpected error

    for header in macho.headers:
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


def _get_incompatible_libs(
    required_version: Version | None,
    version_lib_dict: dict[Version, list[Path]],
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


def _unpack_architectures(
    architecture_versions: Mapping[str, Version],
) -> dict[str, Version]:
    """Return architecture versions derived from their universal forms.

    Examples
    --------
    >>> _unpack_architectures({"arm64": Version("11.0")})
    {'arm64': <Version('11.0')>}
    >>> _unpack_architectures({"universal2": Version("10.5")})
    {'x86_64': <Version('10.5')>, 'arm64': <Version('11.0')>}
    >>> _unpack_architectures({"intel": Version("10.5")})
    {'i386': <Version('10.5')>, 'x86_64': <Version('10.5')>}
    >>> _unpack_architectures({})
    {}
    """
    architecture_versions = {**architecture_versions}
    if "universal2" in architecture_versions:
        architecture_versions["x86_64"] = architecture_versions["universal2"]
        architecture_versions["arm64"] = max(
            architecture_versions["universal2"], Version("11.0")
        )
        del architecture_versions["universal2"]
    if "intel" in architecture_versions:
        architecture_versions["i386"] = architecture_versions["intel"]
        architecture_versions["x86_64"] = architecture_versions["intel"]
        del architecture_versions["intel"]
    return architecture_versions


def _pack_architectures(
    architecture_versions: Mapping[str, Version],
) -> dict[str, Version]:
    """Return architecture versions combined into their universal forms.

    Examples
    --------
    >>> _pack_architectures({"arm64": Version("11.0")})
    {'arm64': <Version('11.0')>}
    >>> _pack_architectures({"i386": Version("10.5"), "x86_64": Version("10.5")})
    {'intel': <Version('10.5')>}
    >>> _pack_architectures({"x86_64": Version("10.5"), "arm64": Version("11.0")})
    {'universal2': <Version('10.5')>}
    >>> _pack_architectures({"x86_64": Version("11.0"), "arm64": Version("12.0")})
    {'x86_64': <Version('11.0')>, 'arm64': <Version('12.0')>}
    >>> _pack_architectures({"i386": Version("11.0"), "x86_64": Version("11.0"), "arm64": Version("11.0")})
    {'i386': <Version('11.0')>, 'universal2': <Version('11.0')>}
    >>> _pack_architectures({})
    {}
    """  # noqa: E501
    architecture_versions = {**architecture_versions}
    if {"x86_64", "arm64"}.issubset(architecture_versions.keys()) and (
        architecture_versions["x86_64"] == architecture_versions["arm64"]
        or architecture_versions["arm64"] == Version("11.0")
    ):
        architecture_versions["universal2"] = architecture_versions["x86_64"]
        del architecture_versions["x86_64"]
        del architecture_versions["arm64"]
    if {"i386", "x86_64"}.issubset(
        architecture_versions.keys()
    ) and architecture_versions["i386"] == architecture_versions["x86_64"]:
        architecture_versions["intel"] = architecture_versions["i386"]
        del architecture_versions["i386"]
        del architecture_versions["x86_64"]
    return architecture_versions


def _calculate_minimum_wheel_name(
    wheel_name: str,
    wheel_dir: Path,
    require_target_macos_version: Version | None,
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
        Any libraries requiring a more modern macOS version than
        `require_target_macos_version`.
    """
    # get platform tag from wheel name using packaging
    if wheel_name.endswith("any.whl"):
        # universal wheel, no need to update the platform tag
        return wheel_name, set()
    wheel_arch_version: Final = _unpack_architectures(
        _get_archs_and_version_from_wheel_name(wheel_name)
    )
    # get the architecture and minimum macOS version from the libraries
    # in the wheel
    all_library_versions: dict[str, dict[Version, list[Path]]] = {}

    for lib in wheel_dir.glob("**/*"):
        if lib.is_dir():
            continue
        for arch, version in _get_macos_min_version(lib):
            all_library_versions.setdefault(arch.lower(), {}).setdefault(
                version, []
            ).append(lib)
            logger.debug(
                "Bundled library info: %s arch=%s target=%s",
                lib.name,
                arch,
                version,
            )

    # Derive architecture requirements from bundled libraries
    arch_version = {
        arch: max(version_libraries.keys())
        for arch, version_libraries in all_library_versions.items()
    }

    # Compare libraries to target macOS version and track incompatibilities
    incompatible_libs: set[tuple[Path, Version]] = set()
    for arch, version_libraries in all_library_versions.items():
        incompatible_libs.update(
            _get_incompatible_libs(
                require_target_macos_version, version_libraries, arch
            )
        )

    # Sanity check, wheels tagged with architectures should have at least one
    # bundled library matching that architecture.
    missing_architectures: Final = (
        wheel_arch_version.keys() - arch_version.keys()
    )
    if missing_architectures:
        raise DelocationError(
            "Failed to find any binary with the required architecture: "
            f"""{",".join(missing_architectures)!r}"""
        )

    # Limit architecture tags to whatever the wheel already claimed to support.
    # Use versions derived from bundled libraries instead of previous wheel tag.
    for arch in arch_version.keys() - wheel_arch_version.keys():
        del arch_version[arch]

    # Wheel platform tags MUST use the macOS release version, not the literal
    # version provided by macOS. Since macOS 11 the minor version number is not
    # part of the macOS release version and MUST be zero for tagging purposes.
    def get_macos_platform_tag(version: Version, architecture: str) -> str:
        """Return the macOS platform tag for this version and architecture.

        `version` will be converted to a release version expected by pip.
        """
        if require_target_macos_version is not None:
            # Version was specified explicitly with MACOSX_DEPLOYMENT_TARGET.
            version = max(version, require_target_macos_version)
        elif version.major >= 11 and version.minor > 0:
            # This is the range where an automatic version is deceptive.
            logger.warning(
                "Wheel will be tagged as supporting macOS %i (%s),"
                " but will not support macOS versions older than %i.%i\n\t"
                "Configure MACOSX_DEPLOYMENT_TARGET to suppress this warning.",
                version.major,
                architecture,
                version.major,
                version.minor,
            )

        minor: Final = 0 if version.major >= 11 else version.minor
        return f"macosx_{version.major}_{minor}_{architecture}"

    platform_tag: Final = ".".join(
        get_macos_platform_tag(version, arch)
        for arch, version in _pack_architectures(arch_version).items()
    )
    prefix: Final = wheel_name.rsplit("-", 1)[0]
    return f"{prefix}-{platform_tag}.whl", incompatible_libs


def _check_and_update_wheel_name(
    wheel_path: Path,
    wheel_dir: Path,
    require_target_macos_version: Version | None,
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
            "\nSet the environment variable"
            f" 'MACOSX_DEPLOYMENT_TARGET={min_valid_version}'"
            " to update minimum supported macOS for this wheel."
        )
    if new_name != wheel_name:
        wheel_path = wheel_path.parent / new_name
    return wheel_path


def _get_delocate_generator_header() -> tuple[str, str]:
    """Return Delocate's version info to be appended to the WHEEL metadata."""
    return ("Generator", f"delocate {__version__}".rstrip())


def _update_wheelfile(wheel_dir: Path, wheel_name: str) -> None:
    """Update the WHEEL file in the wheel directory with updated metadata.

    Updates the platform tag and marks the wheel as modified by delocate.

    Parameters
    ----------
    wheel_dir : Path
        The directory of the unpacked wheel.
    wheel_name : str
        The name of the wheel.
        Used for determining the new platform tag.
    """
    _name, _version, _, platform_tag_set = parse_wheel_filename(wheel_name)
    (file_path,) = wheel_dir.glob("*.dist-info/WHEEL")
    info = read_pkg_info(file_path)

    # Update tags to match current wheel name
    del info["Tag"]
    for tag in platform_tag_set:
        info.add_header("Tag", str(tag))

    # Mark wheel as modifed by this version of Delocate
    delocate_generator = _get_delocate_generator_header()
    if delocate_generator not in info.items():
        info.add_header(*delocate_generator)

    write_pkg_info(file_path, info)


def delocate_wheel(
    in_wheel: str,
    out_wheel: str | None = None,
    lib_sdir: str = ".dylibs",
    lib_filt_func: Callable[[str], bool] | str | None = None,
    copy_filt_func: Callable[[str], bool] | None = filter_system_libs,
    require_archs: Iterable[str] | str | None = None,
    check_verbose: bool | None = None,
    *,
    executable_path: str | None = None,
    ignore_missing: bool = False,
    sanitize_rpaths: bool = False,
    require_target_macos_version: Version | None = None,
) -> dict[str, dict[str, str]]:
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
                f"{lib_path} already exists in wheel but need to copy "
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
        out_wheel_ = Path(out_wheel)
        out_wheel_fixed = _check_and_update_wheel_name(
            out_wheel_, Path(wheel_dir), require_target_macos_version
        )
        if out_wheel_fixed != out_wheel_:
            out_wheel_ = out_wheel_fixed
            in_place = False
        _update_wheelfile(Path(wheel_dir), out_wheel_.name)
        rewrite_record(wheel_dir)
        if len(copied_libs) or not in_place:
            if remove_old:
                os.remove(in_wheel)
                logger.info("Deleted:%s", in_wheel)
            dir2zip(wheel_dir, out_wheel_)
            logger.info("Output:%s", out_wheel_)
    return stripped_lib_dict(copied_libs, wheel_dir + os.path.sep)


def patch_wheel(
    in_wheel: str | os.PathLike[str],
    patch_fname: str | os.PathLike[str],
    out_wheel: str | os.PathLike[str] | None = None,
) -> None:
    """Apply ``-p1`` style patch in `patch_fname` to contents of `in_wheel`.

    If `out_wheel` is None (the default), overwrite the wheel `in_wheel`
    in-place.

    Parameters
    ----------
    in_wheel : str or PathLike
        Filename of wheel to process
    patch_fname : str or PathLike
        Filename of patch file.  Will be applied with ``patch -p1 <
        patch_fname``
    out_wheel : None or str or PathLike
        Filename of patched wheel to write.  If None, overwrite `in_wheel`
    """
    in_wheel = Path(in_wheel).resolve(strict=True)
    patch_fname = Path(patch_fname).resolve(strict=True)
    out_wheel = Path(out_wheel).resolve() if out_wheel is not None else in_wheel
    with InWheel(in_wheel, out_wheel):
        with open(patch_fname, "rb") as f:
            patch_proc = Popen(
                ["patch", "-p1"], stdin=f, stdout=PIPE, stderr=PIPE, text=True
            )
            stdout, _stderr = patch_proc.communicate()
            if patch_proc.returncode != 0:
                raise RuntimeError(f"Patch failed with stdout:\n{stdout}")


_ARCH_LOOKUP = {"intel": ["i386", "x86_64"], "universal2": ["x86_64", "arm64"]}


def check_archs(
    copied_libs: Mapping[str, Mapping[str, str]],
    require_archs: str | Iterable[str] = (),
    stop_fast: bool = False,
) -> set[tuple[str, frozenset[str]] | tuple[str, str, frozenset[str]]]:
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
    bads: list[
        tuple[str, frozenset[str]] | tuple[str, str, frozenset[str]]
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
                "{} needs {} {} missing from {}".format(
                    path_processor(depending_lib),
                    "archs" if len(missing_archs) > 1 else "arch",
                    ", ".join(sorted(missing_archs)),
                    path_processor(depended_lib),
                )
            )
        elif len(result) == 2:
            depending_lib, missing_archs = result
            reports.append(
                "Required {} {} missing from {}".format(
                    "archs" if len(missing_archs) > 1 else "arch",
                    ", ".join(sorted(missing_archs)),
                    path_processor(depending_lib),
                )
            )
        else:
            raise ValueError("Report tuple should be length 2 or 3")
    return "\n".join(sorted(reports))

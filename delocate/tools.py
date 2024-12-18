"""Tools for getting and setting install names."""

from __future__ import annotations

import itertools
import logging
import os
import re
import stat
import subprocess
import time
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from os import PathLike
from os.path import exists, isdir
from os.path import join as pjoin
from pathlib import Path
from typing import (
    Any,
    TypeVar,
)

from typing_extensions import deprecated

T = TypeVar("T")

logger = logging.getLogger(__name__)


class InstallNameError(Exception):
    """Errors reading or modifying macOS install name identifiers."""


@deprecated("Replace this call with subprocess.run")
def back_tick(
    cmd: str | Sequence[str],
    ret_err: bool = False,
    as_str: bool = True,
    raise_err: bool | None = None,
) -> Any:
    """Run command `cmd`, return stdout, or stdout, stderr if `ret_err`.

    Roughly equivalent to ``check_output`` in Python 2.7.

    Parameters
    ----------
    cmd : sequence
        command to execute
    ret_err : bool, optional
        If True, return stderr in addition to stdout.  If False, just return
        stdout
    as_str : bool, optional
        Whether to decode outputs to unicode string on exit.
    raise_err : None or bool, optional
        If True, raise RuntimeError for non-zero return code. If None, set to
        True when `ret_err` is False, False if `ret_err` is True

    Returns
    -------
    out : str or tuple
        If `ret_err` is False, return stripped string containing stdout from
        `cmd`.  If `ret_err` is True, return tuple of (stdout, stderr) where
        ``stdout`` is the stripped stdout, and ``stderr`` is the stripped
        stderr.

    Raises
    ------
    Raises RuntimeError if command returns non-zero exit code and `raise_err`
    is True

    .. deprecated:: 0.10
        This function was deprecated because the return type is too dynamic.
        You should use :func:`subprocess.run` instead.
    """
    if raise_err is None:
        raise_err = False if ret_err else True
    cmd_is_seq = isinstance(cmd, (list, tuple))
    try:
        proc = subprocess.run(
            cmd,
            shell=not cmd_is_seq,
            capture_output=True,
            text=as_str,
            check=raise_err,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"{exc.cmd} returned code {exc.returncode} with error {exc.stderr}"
        )
    if not ret_err:
        return proc.stdout.strip()
    return proc.stdout.strip(), proc.stderr.strip()


def _run(
    cmd: Sequence[str | PathLike[str]], *, check: bool
) -> subprocess.CompletedProcess[str]:
    r"""Run ``cmd`` capturing output and handling non-zero exit codes by default.

    Parameters
    ----------
    cmd : sequence
        The command to execute, passed to `subprocess.run`.
    check : bool, keyword-only
        If True then non-zero exit codes will raise RuntimeError.

    Returns
    -------
    out : CompletedProcess
        A CompletedProcess instance from `subprocess.run`.
        Outputs have been captured, so use ``out.stdout`` and ``out.stderr`` to
        access them.

    Raises
    ------
    RuntimeError:
        If the command returns a non-zero exit code and ``check`` is True.

    Examples
    --------
    >>> _run(["python", "-c", "print('hello')"], check=True)
    CompletedProcess(args=['python', '-c', "print('hello')"], returncode=0, stdout='hello\n', stderr='')
    >>> _run(["python", "-c", "print('hello'); raise SystemExit('world')"], check=True)
    Traceback (most recent call last):
        ...
    RuntimeError: Command ['python', '-c', "print('hello'); raise SystemExit('world')"] failed with non-zero exit code 1.
    stdout:hello
    stderr:world
    """  # noqa: E501
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Command {exc.cmd}"
            f" failed with non-zero exit code {exc.returncode}."
            f"\nstdout:{exc.stdout.strip()}\nstderr:{exc.stderr.strip()}"
        ) from exc


# Mach-O magic numbers. See:
# https://github.com/apple-oss-distributions/xnu/blob/5c2921b07a2480ab43ec66f5b9e41cb872bc554f/EXTERNAL_HEADERS/mach-o/loader.h#L65
# https://github.com/apple-oss-distributions/cctools/blob/658da8c66b4e184458f9c810deca9f6428a773a5/include/mach-o/fat.h#L48
MACHO_MAGIC = frozenset(
    [
        0xFEEDFACE.to_bytes(4, "little"),  # MH_MAGIC
        0xFEEDFACE.to_bytes(4, "big"),  # MH_MAGIC
        0xFEEDFACF.to_bytes(4, "little"),  # MH_MAGIC_64
        0xFEEDFACF.to_bytes(4, "big"),  # MH_MAGIC_64
        0xCAFEBABE.to_bytes(4, "big"),  # FAT_MAGIC (always big-endian)
        0xCAFEBABF.to_bytes(4, "big"),  # FAT_MAGIC_64 (always big-endian)
    ]
)


def _is_macho_file(filename: str | os.PathLike[str]) -> bool:
    """Return True if file at `filename` begins with Mach-O magic number."""
    try:
        with open(filename, "rb") as f:
            header = f.read(4)
            return header in MACHO_MAGIC
    except PermissionError:
        return False
    except FileNotFoundError:
        return False
    except IsADirectoryError:
        return False


def _unique_everseen(iterable: Iterable[T], /) -> Iterator[T]:
    """Yield unique elements, preserving order.

    Simplified version of unique_everseen, see itertools recipes.

    Examples
    --------
    >>> list(_unique_everseen('AAAABBBCCDAABBB'))
    ['A', 'B', 'C', 'D']
    """
    seen: set[T] = set()
    for element in iterable:
        if element not in seen:
            seen.add(element)
            yield element


@deprecated("Use more-itertools unique_everseen instead")
def unique_by_index(sequence: Iterable[T]) -> list[T]:
    """Return unique elements in `sequence` in the order in which they occur.

    Parameters
    ----------
    sequence : iterable

    Returns
    -------
    uniques : list
        unique elements of sequence, ordered by the order in which the element
        occurs in `sequence`

    .. deprecated:: 0.12
        Use more-itertools unique_everseen instead.
    """
    return list(_unique_everseen(sequence))


def chmod_perms(fname):
    """Return permissions relevant to chmod."""
    return stat.S_IMODE(os.stat(fname).st_mode)


def ensure_permissions(mode_flags=stat.S_IWUSR):
    """Decorate a function to ensure a filename has given permissions.

    If changed, original permissions are restored after the decorated
    modification.
    """

    def decorator(f):
        def modify(filename, *args, **kwargs):
            m = chmod_perms(filename) if exists(filename) else mode_flags
            if not m & mode_flags:
                os.chmod(filename, m | mode_flags)
            try:
                return f(filename, *args, **kwargs)
            finally:
                # restore original permissions
                if not m & mode_flags:
                    os.chmod(filename, m)

        return modify

    return decorator


# Open filename, checking for read permission
open_readable = ensure_permissions(stat.S_IRUSR)(open)

# Open filename, checking for read / write permission
open_rw = ensure_permissions(stat.S_IRUSR | stat.S_IWUSR)(open)

# For backward compatibility
ensure_writable = ensure_permissions()

# otool on 10.15 appends more information after versions.
IN_RE = re.compile(
    r"(.*) \(compatibility version (\d+\.\d+\.\d+), "
    r"current version (\d+\.\d+\.\d+)(?:, \w+)?\)"
)


def parse_install_name(line: str) -> tuple[str, str, str]:
    """Parse a line of install name output.

    Parameters
    ----------
    line : str
        line of install name output from ``otool``

    Returns
    -------
    libname : str
        library install name
    compat_version : str
        compatibility version
    current_version : str
        current version

    Examples
    --------
    >>> parse_install_name("/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)")
    ('/usr/lib/libc++.1.dylib', '1.0.0', '905.6.0')
    """  # noqa: E501
    line = line.strip()
    match = IN_RE.match(line)
    if not match:
        raise ValueError(f"Could not parse {line!r}")
    libname, compat_version, current_version = match.groups()
    return libname, compat_version, current_version


_OTOOL_ARCHITECTURE_RE = re.compile(
    r"^(?P<name>.*?)(?: \(architecture (?P<architecture>\w+)\))?:$"
)
"""Matches the library separator line in 'otool -L'-like outputs.

Examples
--------
>>> match = _OTOOL_ARCHITECTURE_RE.match("example.so (architecture x86_64):")
>>> match["name"]
'example.so'
>>> match["architecture"]
'x86_64'
>>> match = _OTOOL_ARCHITECTURE_RE.match("example.so:")
>>> match["name"]
'example.so'
>>> match["architecture"] is None
True
"""


def _parse_otool_listing(stdout: str) -> dict[str, list[str]]:
    '''Parse the output of otool lists.

    Parameters
    ----------
    stdout : str
        A decoded stdout of commands like 'otool -L' or 'otool -D' to be parsed.

    Returns
    -------
    otool_out : dict of list of str
        The dictionary key is the architecture, e.g. 'x86_64'.
        If no architecture is parsed then the key is ''.
        The values are a list of strings associated with the key.

    Examples
    --------
    >>> _parse_otool_listing("""
    ... example.so (architecture x86_64):
    ... \titem_1
    ... \titem_2
    ... example.so (architecture arm64):
    ... \titem_3
    ... \titem_4
    ... """)
    {'x86_64': ['item_1', 'item_2'], 'arm64': ['item_3', 'item_4']}
    >>> _parse_otool_listing("""
    ... example.so:
    ... \titem_1
    ... """)
    {'': ['item_1']}
    >>> _parse_otool_listing("""
    ... example.so (architecture x86_64):
    ... example.so (architecture arm64):
    ... """)
    {'x86_64': [], 'arm64': []}
    >>> _parse_otool_listing("")
    Traceback (most recent call last):
        ...
    RuntimeError: Missing file/architecture header:...
    >>> _parse_otool_listing("""
    ... example.so (architecture arm64):
    ... example.so (architecture arm64):
    ... """)
    Traceback (most recent call last):
        ...
    RuntimeError: Input has duplicate architectures for ...
    '''  # noqa: D301
    stdout = stdout.strip()
    out: dict[str, list[str]] = {}
    lines = stdout.split("\n")
    while lines:
        # Detect and parse the name/arch header line.
        match_arch = _OTOOL_ARCHITECTURE_RE.match(lines.pop(0))
        if not match_arch:
            raise RuntimeError(f"Missing file/architecture header:\n{stdout}")
        current_arch: str | None = match_arch["architecture"]
        if current_arch is None:
            current_arch = ""
        if current_arch in out:
            raise RuntimeError(
                "Input has duplicate architectures for"
                f" {current_arch!r}:\n{stdout}"
            )
        out[current_arch] = []
        # Collect lines until the next header or the end.
        while lines and not lines[0].endswith(":"):
            out[current_arch].append(lines.pop(0).strip())
    return out


@deprecated("This function is no longer needed and should not be used")
def _check_ignore_archs(input: dict[str, T]) -> T:
    """Merge architecture outputs for functions which don't support multiple.

    This is used to maintain backward compatibility inside of functions which
    never supported multiple architectures.  You should not call this function
    from new functions.

    Parameters
    ----------
    input : dict of T
        A dict similar to the return value of :func:`_parse_otool_listing`.
        Must be non-empty.

    Returns
    -------
    out : T
        One of the values from ``input``.
        Multiple architectures combined into a single output where possible.

    Raises
    ------
    NotImplementedError
        If ``input`` has different values per-architecture.

    Examples
    --------
    >>> values = {"a": 10, "b": 10}
    >>> _check_ignore_archs(values)
    10
    >>> values
    {'a': 10, 'b': 10}
    >>> _check_ignore_archs({"": ["1", "2", "2"]})
    ['1', '2', '2']
    >>> _check_ignore_archs({"a": "1", "b": "not 1"})
    Traceback (most recent call last):
        ...
    NotImplementedError: ...
    """
    first, *rest = input.values()
    if any(first != others for others in rest):
        raise NotImplementedError(
            "This function does not support separate values per-architecture:"
            f" {input}"
        )
    return first


def _parse_otool_install_names(
    stdout: str,
) -> dict[str, list[tuple[str, str, str]]]:
    '''Parse the stdout of 'otool -L' and return.

    Parameters
    ----------
    stdout : str
        A decoded stdout of 'otool -L' to be parsed.

    Returns
    -------
    install_name_info : dict of list of (libname, compat_v, current_v) tuples
        The dictionary key is the architecture, e.g. 'x86_64'.
        If no architecture is parsed then the key is ''.
        See :func:`parse_install_name` for more info on the tuple values.

    Examples
    --------
    >>> _parse_otool_install_names("""
    ... example.so (architecture x86_64):
    ... \t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
    ... \t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
    ... example.so (architecture arm64):
    ... \t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
    ... \t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
    ... """)
    {'x86_64': [('/usr/lib/libc++.1.dylib', '1.0.0', '905.6.0'), ('/usr/lib/libSystem.B.dylib', '1.0.0', '1292.100.5')], 'arm64': [('/usr/lib/libc++.1.dylib', '1.0.0', '905.6.0'), ('/usr/lib/libSystem.B.dylib', '1.0.0', '1292.100.5')]}
    >>> _parse_otool_install_names("""
    ... example.so:
    ... \t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
    ... \t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
    ... """)
    {'': [('/usr/lib/libc++.1.dylib', '1.0.0', '905.6.0'), ('/usr/lib/libSystem.B.dylib', '1.0.0', '1292.100.5')]}
    '''  # noqa: E501, D301
    out: dict[str, list[tuple[str, str, str]]] = {}
    for arch, install_names in _parse_otool_listing(stdout).items():
        out[arch] = [parse_install_name(name) for name in install_names]
    return out


# otool -L strings indicating this is not an object file. The string changes
# with different otool versions.
RE_PERM_DEN = re.compile(r"Permission denied[.) ]*$")
BAD_OBJECT_TESTS = [
    # otool version cctools-862
    lambda s: "is not an object file" in s,
    # cctools-862 (.ico)
    lambda s: "The end of the file was unexpectedly encountered" in s,
    # cctools-895
    lambda s: "The file was not recognized as a valid object file" in s,
    # 895 binary file
    lambda s: "Invalid data was encountered while parsing the file" in s,
    # cctools-900
    lambda s: "Object is not a Mach-O file type" in s,
    # cctools-949
    lambda s: "object is not a Mach-O file type" in s,
    # File may not have read permissions
    lambda s: RE_PERM_DEN.search(s) is not None,
]


# Sometimes the line starts with (architecture arm64) and sometimes not
# The regex is used for matching both
_LINE0_RE = re.compile(r"^(?: \(architecture .*\))?:(?P<further_report>.*)")


def _line0_says_object(
    stdout_stderr: str, filename: str | PathLike[str]
) -> bool:
    """Return True if an output is for an object and matches filename.

    Parameters
    ----------
    stdout_stderr : str or PathLike
        The combined stdout/stderr streams from ``otool``.
    filename: str
        The name of the file queried by ``otool``.

    Returns
    -------
    is_object : bool
        True if this is a valid object.
        False if the output clearly suggests this is some other kind of file.

    Raises
    ------
    InstallNameError
        On any unexpected output which would leave the return value unknown.
    """
    filename = str(Path(filename))
    line0 = stdout_stderr.strip().split("\n", 1)[0]
    for test in BAD_OBJECT_TESTS:
        if test(line0):
            # Output suggests that this is not a valid object file.
            return False
    if line0.startswith("Archive :"):
        # nothing to do for static libs
        return False
    if not line0.startswith(filename):
        raise InstallNameError("Unexpected first line: " + line0)
    match = _LINE0_RE.match(line0[len(filename) :])
    if not match:
        raise InstallNameError("Unexpected first line: " + line0)
    further_report = match.group("further_report")
    if further_report == "":
        return True
    raise InstallNameError(
        f'Too ignorant to know what "{further_report}" means'
    )


def _get_install_names(
    filename: str | PathLike[str],
) -> dict[str, list[str]]:
    """Return install names from library named in `filename`.

    Returns tuple of install names.

    tuple will be empty if no install names, or if this is not an object file.

    Parameters
    ----------
    filename : str or PathLike
        filename of library

    Returns
    -------
    install_names : tuple
        tuple of install names for library `filename`

    Raises
    ------
    InstallNameError
        On any unexpected output from ``otool``.
    """
    if not _is_macho_file(filename):
        return {}
    otool = _run(["otool", "-arch", "all", "-m", "-L", filename], check=False)
    if not _line0_says_object(otool.stdout or otool.stderr, filename):
        return {}
    install_ids = _get_install_ids(filename)
    # Collect install names for each architecture
    all_names: dict[str, list[str]] = {}
    for arch, names_data in _parse_otool_install_names(otool.stdout).items():
        names = [name for name, _, _ in names_data]
        # Remove redundant install id from the install names.
        if arch in install_ids:
            if names[0] != install_ids[arch]:
                raise InstallNameError(
                    f"Expected {install_ids[arch]!r} to be first in {names}"
                )
            names = names[1:]
        all_names[arch] = names

    return all_names


def get_install_names(filename: str | PathLike[str]) -> tuple[str, ...]:
    """Return install names from library named in `filename`.

    Returns tuple of install names.

    tuple will be empty if no install names, or if this is not an object file.

    Parameters
    ----------
    filename : str or PathLike
        filename of library

    Returns
    -------
    install_names : tuple
        tuple of install names for library `filename`

    Raises
    ------
    InstallNameError
        On any unexpected output from ``otool``.
    """
    return tuple(
        _unique_everseen(
            itertools.chain(*_get_install_names(filename).values())
        )
    )


@deprecated("This function was replaced by _get_install_ids")
def get_install_id(filename: str) -> str | None:
    """Return install id from library named in `filename`.

    Returns None if no install id, or if this is not an object file.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_id : str
        install id of library `filename`, or None if no install id

    Raises
    ------
    NotImplementedError
        If ``filename`` has different install ids per-architecture.

    .. deprecated:: 0.12
        This function has been replaced by the private function
        `_get_install_ids`.
    """
    install_ids = _get_install_ids(filename)
    if not install_ids:
        return None  # No install ids or nothing returned.
    return _check_ignore_archs(install_ids)


def _get_install_ids(filename: str | PathLike[str]) -> dict[str, str]:
    """Return the install ids of a library.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_ids : dict
        install ids of library `filename`.
        The key is the architecture which is '' if none is provided by otool.
        The value is the install id for that architecture.
        If the library has no install ids then an empty dict is returned.

    Raises
    ------
    InstallNameError
        On any unexpected output from ``otool``.
    """
    if not _is_macho_file(filename):
        return {}
    otool = _run(["otool", "-arch", "all", "-m", "-D", filename], check=False)
    if not _line0_says_object(otool.stdout or otool.stderr, filename):
        return {}
    out = {}
    for arch, my_id_list in _parse_otool_listing(otool.stdout).items():
        if not my_id_list:
            continue  # No install ID.
        if len(my_id_list) != 1:
            raise InstallNameError(
                "Expected at most 1 value for a libraries install ID,"
                f" got {my_id_list}"
            )
        out[arch] = my_id_list[0]
    return out


@ensure_writable
def set_install_name(
    filename: str, oldname: str, newname: str, ad_hoc_sign: bool = True
) -> None:
    """Set install name `oldname` to `newname` in library filename.

    Parameters
    ----------
    filename : str
        filename of library
    oldname : str
        current install name in library
    newname : str
        replacement name for `oldname`
    ad_hoc_sign : {True, False}, optional
        If True, sign library with ad-hoc signature
    """
    names = get_install_names(filename)
    if oldname not in names:
        raise InstallNameError(f"{oldname} not in install names for {filename}")
    _run(
        ["install_name_tool", "-change", oldname, newname, filename], check=True
    )
    if ad_hoc_sign:
        # ad hoc signature is represented by a dash
        # https://developer.apple.com/documentation/security/seccodesignatureflags/kseccodesignatureadhoc
        replace_signature(filename, "-")


@ensure_writable
def set_install_id(
    filename: str | PathLike[str], install_id: str, ad_hoc_sign: bool = True
):
    """Set install id for library named in `filename`.

    Parameters
    ----------
    filename : str or PathLike
        filename of library
    install_id : str
        install id for library `filename`
    ad_hoc_sign : {True, False}, optional
        If True, sign library with ad-hoc signature

    Raises
    ------
    RuntimeError if `filename` has not install id
    """
    if not _get_install_ids(filename):
        raise InstallNameError(f"{filename} has no install id")
    _run(["install_name_tool", "-id", install_id, filename], check=True)
    if ad_hoc_sign:
        replace_signature(filename, "-")


RPATH_RE = re.compile(r"path (?P<rpath>.*) \(offset \d+\)")


def _parse_otool_rpaths(stdout: str) -> dict[str, list[str]]:
    '''Return the rpaths of the library `filename`.

    Parameters
    ----------
    stdout : str
        The decoded stdout of an 'otool -l' command.

    Returns
    -------
    rpaths : dict of list of str
        Where the key is the architecture and the value is the list of paths.
        If the library has no rpaths then the values will be an empty list.

    Examples
    --------
    >>> _parse_otool_rpaths("""
    ... example.so:
    ...     cmd LC_RPATH
    ... cmdsize 0
    ...    path /example/path (offset 0)
    ...     cmd LC_RPATH
    ... cmdsize 0
    ...    path @loader_path (offset 0)
    ... """)
    {'': ['/example/path', '@loader_path']}
    >>> _parse_otool_rpaths("""example.so:""")  # No rpaths.
    {'': []}
    >>> _parse_otool_rpaths("""
    ... example.so (architecture x86_64):
    ...     cmd LC_RPATH
    ... cmdsize 0
    ...    path path/x86_64 (offset 0)
    ... example.so (architecture arm64):
    ...     cmd LC_RPATH
    ... cmdsize 0
    ...    path path/arm64 (offset 0)
    ... """)
    {'x86_64': ['path/x86_64'], 'arm64': ['path/arm64']}
    '''
    rpaths: dict[str, list[str]] = {}
    for arch, lines in _parse_otool_listing(stdout).items():
        rpaths[arch] = []
        line_no = 0
        while line_no < len(lines):
            line = lines[line_no]
            line_no += 1
            if line != "cmd LC_RPATH":
                continue
            cmdsize, path = lines[line_no : line_no + 2]
            assert cmdsize.startswith("cmdsize "), "Could not parse:\n{stdout}"
            match_rpath = RPATH_RE.match(path)
            assert match_rpath, "Could not parse:\n{stdout}"
            rpaths[arch].append(match_rpath["rpath"])
            line_no += 2
    return rpaths


def _get_rpaths(
    filename: str | PathLike[str],
) -> dict[str, list[str]]:
    """Return the rpaths from the library `filename` organized by architecture.

    If `filename` is not a library then the returned dict will be empty.
    Duplicate rpaths will be returned if there are duplicate rpaths in the
    Mach-O binary.

    Parameters
    ----------
    filename
        filename of library

    Returns
    -------
    rpaths
        A dict of rpaths, the key is the architecture and the values are a
        sequence of directories.

    Raises
    ------
    InstallNameError
        On any unexpected output from ``otool``.
    """
    if not _is_macho_file(filename):
        return {}
    otool = _run(["otool", "-arch", "all", "-m", "-l", filename], check=False)
    if not _line0_says_object(otool.stdout or otool.stderr, filename):
        return {}

    return _parse_otool_rpaths(otool.stdout)


@deprecated("This function has been replaced by _get_rpaths")
def get_rpaths(filename: str | PathLike[str]) -> tuple[str, ...]:
    """Return a tuple of rpaths from the library `filename`.

    If `filename` is not a library then the returned tuple will be empty.

    Parameters
    ----------
    filename : str or PathLike
        filename of library

    Returns
    -------
    rpath : tuple
        rpath paths in `filename`

    Raises
    ------
    NotImplementedError
        If ``filename`` has different rpaths per-architecture.
    InstallNameError
        On any unexpected output from ``otool``.

    .. deprecated:: 0.12
        This function has been replaced by the private function `_get_rpaths`.
    """
    # Simply return all rpaths ignoring architectures
    return tuple(
        _unique_everseen(itertools.chain(*_get_rpaths(filename).values()))
    )


def get_environment_variable_paths() -> tuple[str, ...]:
    """Return a tuple of entries in `DYLD_LIBRARY_PATH` and `DYLD_FALLBACK_LIBRARY_PATH`.

    This will allow us to search those locations for dependencies of libraries
    as well as `@rpath` entries.

    Returns
    -------
    env_var_paths : tuple
        path entries in environment variables
    """  # noqa: E501
    # We'll search the extra library paths in a specific order:
    # DYLD_LIBRARY_PATH and then DYLD_FALLBACK_LIBRARY_PATH
    env_var_paths = []
    extra_paths = ["DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"]
    for pathname in extra_paths:
        path_contents = os.environ.get(pathname)
        if path_contents is not None:
            for path in path_contents.split(os.pathsep):
                env_var_paths.append(path)
    return tuple(env_var_paths)


@ensure_writable
def add_rpath(filename: str, newpath: str, ad_hoc_sign: bool = True) -> None:
    """Add rpath `newpath` to library `filename`.

    Parameters
    ----------
    filename : str
        filename of library
    newpath : str
        rpath to add
    ad_hoc_sign : {True, False}, optional
        If True, sign file with ad-hoc signature
    """
    _run(["install_name_tool", "-add_rpath", newpath, filename], check=True)
    if ad_hoc_sign:
        replace_signature(filename, "-")


@ensure_writable
def _delete_rpaths(
    filename: str, rpaths: Iterable[str], ad_hoc_sign: bool = True
) -> None:
    """Remove rpath `newpath` from library `filename`.

    Parameters
    ----------
    filename : str
        filename of library
    rpaths : Iterable[str]
        rpaths to delete
    ad_hoc_sign : {True, False}, optional
        If True, sign file with ad-hoc signature
    """
    for rpath in rpaths:
        logger.info("Sanitize: Deleting rpath %r from %r", rpath, filename)
        # We can run these as one command to install_name_tool if there are
        # no duplicates. When there are duplicates, we need to delete them
        # separately.
        _run(
            ["install_name_tool", "-delete_rpath", rpath, filename],
            check=True,
        )
    if ad_hoc_sign:
        replace_signature(filename, "-")


_SANITARY_RPATH = re.compile(r"^@loader_path/|^@executable_path/")
"""Matches rpaths which are considered sanitary."""


def _is_rpath_sanitary(rpath: str) -> bool:
    """Return True if `rpath` is considered sanitary.

    Includes only paths relative to `@executable_path` or `@loader_path`.

    Excludes absolute and relative (to the current directory) paths.

    Examples
    --------
    >>> _is_rpath_sanitary("/absolute/path")
    False
    >>> _is_rpath_sanitary("relative/path")
    False
    >>> _is_rpath_sanitary("@loader_path/../example")
    True
    >>> _is_rpath_sanitary("@executable_path/../example")
    True
    >>> _is_rpath_sanitary("fake/@loader_path/../example")
    False
    >>> _is_rpath_sanitary("@other_path/../example")
    False
    """
    return bool(_SANITARY_RPATH.match(rpath))


@ensure_writable
def _remove_absolute_rpaths(filename: str, ad_hoc_sign: bool = True) -> None:
    """Remove absolute filename rpaths in `filename`.

    Parameters
    ----------
    filename : str
        filename of library
    ad_hoc_sign : {True, False}, optional
        If True, sign file with ad-hoc signature
    """
    _delete_rpaths(
        filename,
        (
            rpath
            for rpath in get_rpaths(filename)
            if not _is_rpath_sanitary(rpath)
        ),
        ad_hoc_sign,
    )


def zip2dir(
    zip_fname: str | PathLike[str], out_dir: str | PathLike[str]
) -> None:
    """Extract `zip_fname` into output directory `out_dir`.

    Parameters
    ----------
    zip_fname : str or Path-like
        Filename of zip archive to write
    out_dir : str or Path-like
        Directory path containing files to go in the zip archive
    """
    # The zipfile module does not preserve permissions correctly
    # http://bugs.python.org/issue15795
    # external_attr is not well documented but you can learn about it here
    # https://unix.stackexchange.com/questions/14705/the-zip-formats-external-file-attribute
    with zipfile.ZipFile(zip_fname, "r") as zip:
        for name in zip.namelist():
            member = zip.getinfo(name)
            extracted_path = zip.extract(member, out_dir)
            unix_attrs = member.external_attr >> 16
            if member.is_dir():
                os.chmod(extracted_path, 0o755)
            elif unix_attrs != 0:
                permissions = unix_attrs & 0o777
                os.chmod(extracted_path, permissions)
            # Restore timestamp
            modified_time = datetime(*member.date_time).timestamp()
            os.utime(extracted_path, (modified_time, modified_time))


_ZIP_TIMESTAMP_MIN = 315532800  # 1980-01-01 00:00:00 UTC
_DateTuple = tuple[int, int, int, int, int, int]


def _get_zip_datetime(
    date_time: _DateTuple | None = None,
) -> _DateTuple | None:
    """Return ``SOURCE_DATE_EPOCH`` if set, otherwise return `date_time`.

    https://reproducible-builds.org/docs/source-date-epoch/

    Parameters
    ----------
    date_time : tuple of int, optional
        Datetime tuple ``(Y, m, d, H, M, S)``.

    Returns
    -------
    zip_date_time : tuple of int, optional
        Datetime tuple corresponding to the ``SOURCE_DATE_EPOCH``
        environment variable if set, otherwise the input `date_time`.
    """
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        timestamp = max(int(source_date_epoch), _ZIP_TIMESTAMP_MIN)
        date_time = time.gmtime(timestamp)[0:6]
    return date_time


def dir2zip(
    in_dir: str | PathLike[str],
    zip_fname: str | PathLike[str],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    compress_level: int = -1,
    date_time: _DateTuple | None = None,
) -> None:
    """Make a zip file `zip_fname` with contents of directory `in_dir`.

    The recorded filenames are relative to `in_dir`, so doing a standard zip
    unpack of the resulting `zip_fname` in an empty directory will result in
    the original directory contents.

    Parameters
    ----------
    in_dir : str or Path-like
        Directory path containing files to go in the zip archive
    zip_fname : str or Path-like
        Filename of zip archive to write
    compression : int, optional, keyword-only
        The zipfile compression type used.
    compress_level : int, optional, keyword-only
        The compression level used for this archive.
    date_time : tuple of int, optional, keyword-only
        Datetime tuple ``(Y, m, d, H, M, S)`` for all recorded entries.
    """
    date_time = _get_zip_datetime(date_time)
    with zipfile.ZipFile(
        zip_fname, "w", compression=compression, compresslevel=compress_level
    ) as zip:
        for root, dirs, files in os.walk(in_dir):
            for dir in dirs:
                dir_path = Path(root, dir)
                out_dir_name = str(dir_path.relative_to(in_dir)) + "/"
                zip_info = zipfile.ZipInfo.from_file(dir_path, out_dir_name)
                if date_time is not None:
                    zip_info.date_time = date_time
                zip.writestr(zip_info, b"")
            for file in files:
                file_path = Path(root, file)
                out_file_path = file_path.relative_to(in_dir)
                zip_info = zipfile.ZipInfo.from_file(file_path, out_file_path)
                if date_time is not None:
                    zip_info.date_time = date_time
                zip.writestr(
                    zip_info,
                    file_path.read_bytes(),
                    compress_type=compression,
                    compresslevel=compress_level,
                )


def find_package_dirs(root_path: str) -> set[str]:
    """Find python package directories in directory `root_path`.

    Parameters
    ----------
    root_path : str
        Directory to search for package subdirectories

    Returns
    -------
    package_sdirs : set
        Set of strings where each is a subdirectory of `root_path`, containing
        an ``__init__.py`` file.  Paths prefixed by `root_path`
    """
    package_sdirs = set()
    for entry in os.listdir(root_path):
        fname = entry if root_path == "." else pjoin(root_path, entry)
        if isdir(fname) and exists(pjoin(fname, "__init__.py")):
            package_sdirs.add(fname)
    return package_sdirs


def cmp_contents(filename1, filename2):
    """Return True if contents of the files are the same.

    Parameters
    ----------
    filename1 : str
        filename of first file to compare
    filename2 : str
        filename of second file to compare

    Returns
    -------
    tf : bool
        True if binary contents of `filename1` is same as binary contents of
        `filename2`, False otherwise.
    """
    with open_readable(filename1, "rb") as fobj:
        contents1 = fobj.read()
    with open_readable(filename2, "rb") as fobj:
        contents2 = fobj.read()
    return contents1 == contents2


def get_archs(libname: str) -> frozenset[str]:
    """Return architecture types from library `libname`.

    Parameters
    ----------
    libname : str
        filename of binary for which to return arch codes

    Returns
    -------
    arch_names : frozenset
        Empty (frozen)set if no arch codes.  If not empty, contains one or more
        of 'ppc', 'ppc64', 'i386', 'x86_64', 'arm64'.
    """
    if not exists(libname):
        raise RuntimeError(libname + " is not a file")
    try:
        lipo = _run(["lipo", "-info", libname], check=True)
        stdout = lipo.stdout.strip()
    except RuntimeError:
        return frozenset()
    lines = [line.strip() for line in stdout.split("\n") if line.strip()]
    # For some reason, output from lipo -info on .a file generates this line
    if lines[0] == f"input file {libname} is not a fat file":
        line = lines[1]
    else:
        assert len(lines) == 1
        line = lines[0]
    for reggie in (
        f"Non-fat file: {re.escape(libname)} is architecture: (.*)",
        f"Architectures in the fat file: {re.escape(libname)} are: (.*)",
    ):
        match = re.match(reggie, line)
        if match is not None:
            return frozenset(match.groups()[0].split(" "))
    raise ValueError(f"Unexpected output: '{stdout}' for {libname}")


@deprecated("Call lipo directly")
def lipo_fuse(
    in_fname1: str | PathLike[str],
    in_fname2: str | PathLike[str],
    out_fname: str | PathLike[str],
    ad_hoc_sign: bool = True,
) -> str:
    """Use lipo to merge libs `filename1`, `filename2`, store in `out_fname`.

    Parameters
    ----------
    in_fname1 : str or PathLike
        filename of library
    in_fname2 : str or PathLike
        filename of library
    out_fname : str or PathLike
        filename to which to write new fused library
    ad_hoc_sign : {True, False}, optional
        If True, sign file with ad-hoc signature

    Raises
    ------
    RuntimeError
        If the lipo command exits with an error.
    """
    lipo = _run(
        ["lipo", "-create", in_fname1, in_fname2, "-output", out_fname],
        check=True,
    )
    if ad_hoc_sign:
        replace_signature(out_fname, "-")
    return lipo.stdout.strip()


@ensure_writable
def replace_signature(filename: str | PathLike[str], identity: str) -> None:
    """Replace the signature of a binary file using `identity`.

    See the codesign documentation for more info.

    Parameters
    ----------
    filename : str
        Filepath to a binary file.
    identity : str
        The signing identity to use.
    """
    _run(["codesign", "--force", "--sign", identity, filename], check=True)


def validate_signature(filename: str) -> None:
    """Remove invalid signatures from a binary file.

    If the file signature is missing or valid then it will be ignored.

    Invalid signatures are replaced with an ad-hoc signature.
    This is the closest you can get to removing a signature on MacOS.

    Parameters
    ----------
    filename : str
        Filepath to a binary file
    """
    codesign = _run(["codesign", "--verify", filename], check=False)
    if not codesign.stderr:
        return  # The existing signature is valid
    if "code object is not signed at all" in codesign.stderr:
        return  # File has no signature, and adding a new one isn't necessary

    # This file's signature is invalid and needs to be replaced
    replace_signature(filename, "-")  # Replace with an ad-hoc signature

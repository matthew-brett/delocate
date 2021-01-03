""" Tools for getting and setting install names """

from subprocess import Popen, PIPE

import os
from os.path import join as pjoin, relpath, isdir, exists
import zipfile
import re
import stat
import time
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    FrozenSet,
    Text,
    Tuple,
    TypeVar,
    Union,
)


T = TypeVar("T")
F = TypeVar('F', bound=Callable[..., Any])


class InstallNameError(Exception):
    pass


def run_call(cmd):
    # type: (Union[Text, Sequence[Text]]) -> Tuple[int, Text, Text]
    """ Run a command and return the exit code as well as stdout and stderr.

    If unsure, then use the `check_call` function instead.

    Parameters
    ----------
    cmd : sequence
        command to execute

    Returns
    -------
    returncode : int
        The return code the call exited with.
    stdout : str
        The stripped output from the calls stdout pipe.
    stderr : str
        The stripped output from the calls stderr pipe.
    """
    cmd_is_seq = not isinstance(cmd, str)
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=not cmd_is_seq,
                 universal_newlines=True)
    out = ""
    err = ""
    while proc.returncode is None:
        out_, err_ = proc.communicate()
        out += out_
        err += err_
    return proc.returncode, out.strip(), err.strip()


def check_call(cmd):
    # type: (Union[Text, Sequence[Text]]) -> Text
    """ Run a command and return the output on success or raise an exception on
    an error.

    Roughly equivalent to ``check_output`` in Python 2.7

    Parameters
    ----------
    cmd : sequence
        command to execute

    Returns
    -------
    stdout : str
        The stripped output from the calls stdout pipe.

    Raises
    ------
    RuntimeError
        If the call returns a non-zero exit code.
    """
    returncode, out, err = run_call(cmd)
    if returncode != 0:
        cmd_is_seq = not isinstance(cmd, str)
        cmd_str = ' '.join(cmd) if cmd_is_seq else cmd
        raise RuntimeError(
            '{0} returned code {1} with error {2}'.format(
                cmd_str, returncode, err
            )
        )
    return out


def unique_by_index(sequence):
    # type: (Iterable[T]) -> List[T]
    """ unique elements in `sequence` in the order in which they occur

    Parameters
    ----------
    sequence : iterable

    Returns
    -------
    uniques : list
        unique elements of sequence, ordered by the order in which the element
        occurs in `sequence`
    """
    uniques = []
    for element in sequence:
        if element not in uniques:
            uniques.append(element)
    return uniques


def chmod_perms(fname):
    # type: (Text) -> int
    # Permissions relevant to chmod
    return stat.S_IMODE(os.stat(fname).st_mode)


def ensure_permissions(mode_flags=stat.S_IWUSR):
    # type: (int) -> Callable[[F], F]
    """decorator to ensure a filename has given permissions.

    If changed, original permissions are restored after the decorated
    modification.
    """

    def decorator(f):
        # type: (F) -> F
        def modify(filename, *args, **kwargs):
            # type: (str, *Any, **Any) -> Any
            m = chmod_perms(filename) if exists(filename) else mode_flags
            if not m & mode_flags:
                os.chmod(filename, m | mode_flags)
            try:
                return f(filename, *args, **kwargs)
            finally:
                # restore original permissions
                if not m & mode_flags:
                    os.chmod(filename, m)
        return modify  # type: ignore  # Cast to F

    return decorator


# Open filename, checking for read permission
open_readable = ensure_permissions(stat.S_IRUSR)(open)

# Open filename, checking for read / write permission
open_rw = ensure_permissions(stat.S_IRUSR | stat.S_IWUSR)(open)

# For backward compatibility
ensure_writable = ensure_permissions()

# otool on 10.15 appends more information after versions.
IN_RE = re.compile(r"(.*) \(compatibility version (\d+\.\d+\.\d+), "
                   r"current version (\d+\.\d+\.\d+)(?:, \w+)?\)")


def parse_install_name(line):
    # type: (Text) -> Tuple[Text, Text, Text]
    """ Parse a line of install name output

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
    """
    line = line.strip()
    match = IN_RE.match(line)
    if not match:
        raise RuntimeError("Could not parse {0!r}.".format(line))
    libname, compat_version, current_version = match.groups()
    return libname, compat_version, current_version


# otool -L strings indicating this is not an object file. The string changes
# with different otool versions.
RE_PERM_DEN = re.compile(r"Permission denied[.) ]*$")
BAD_OBJECT_TESTS = [
    # otool version cctools-862
    lambda s: 'is not an object file' in s,
    # cctools-862 (.ico)
    lambda s: 'The end of the file was unexpectedly encountered' in s,
    # cctools-895
    lambda s: 'The file was not recognized as a valid object file' in s,
    # 895 binary file
    lambda s: 'Invalid data was encountered while parsing the file' in s,
    # cctools-900
    lambda s: 'Object is not a Mach-O file type' in s,
    # cctools-949
    lambda s: 'object is not a Mach-O file type' in s,
    # File may not have read permissions
    lambda s: RE_PERM_DEN.search(s) is not None
]  # type: List[Callable[[Text], bool]]


def _cmd_out_err(cmd):
    # type: (Union[Text, Sequence[Text]]) -> List[Text]
    # Run command, return stdout or stderr if stdout is empty
    _, out, err = run_call(cmd)
    out = err if not len(out) else out
    return out.split('\n')


def _line0_says_object(line0, filename):
    # type: (Text, Text) -> bool
    line0 = line0.strip()
    for test in BAD_OBJECT_TESTS:
        if test(line0):
            return False
    if line0.startswith('Archive :'):
        # nothing to do for static libs
        return False
    if not line0.startswith(filename + ':'):
        raise InstallNameError('Unexpected first line: ' + line0)
    further_report = line0[len(filename) + 1:]
    if further_report == '':
        return True
    raise InstallNameError(
        'Too ignorant to know what "{0}" means'.format(further_report))


def get_install_names(filename):
    # type: (Text) -> Tuple[Text, ...]
    """ Return install names from library named in `filename`

    Returns tuple of install names

    tuple will be empty if no install names, or if this is not an object file.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_names : tuple
        tuple of install names for library `filename`
    """
    lines = _cmd_out_err(['otool', '-L', filename])
    if not _line0_says_object(lines[0], filename):
        return ()
    names = tuple(parse_install_name(line)[0] for line in lines[1:])
    install_id = get_install_id(filename)
    if install_id is not None:
        assert names[0] == install_id
        return names[1:]
    return names


def get_install_id(filename):
    # type: (Text) -> Optional[Text]
    """ Return install id from library named in `filename`

    Returns None if no install id, or if this is not an object file.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_id : str
        install id of library `filename`, or None if no install id
    """
    lines = _cmd_out_err(['otool', '-D', filename])
    if not _line0_says_object(lines[0], filename):
        return None
    if len(lines) == 1:
        return None
    if len(lines) != 2:
        raise InstallNameError('Unexpected otool output ' + '\n'.join(lines))
    return lines[1].strip()


@ensure_writable
def set_install_name(filename, oldname, newname):
    # type: (Text, Text, Text) -> None
    """ Set install name `oldname` to `newname` in library filename

    Parameters
    ----------
    filename : str
        filename of library
    oldname : str
        current install name in library
    newname : str
        replacement name for `oldname`
    """
    names = get_install_names(filename)
    if oldname not in names:
        raise InstallNameError('{0} not in install names for {1}'.format(
            oldname, filename))
    check_call(['install_name_tool', '-change', oldname, newname, filename])


@ensure_writable
def set_install_id(filename, install_id):
    # type: (Text, Text) -> None
    """ Set install id for library named in `filename`

    Parameters
    ----------
    filename : str
        filename of library
    install_id : str
        install id for library `filename`

    Raises
    ------
    RuntimeError if `filename` has not install id
    """
    if get_install_id(filename) is None:
        raise InstallNameError('{0} has no install id'.format(filename))
    check_call(['install_name_tool', '-id', install_id, filename])


RPATH_RE = re.compile(r"path (.*) \(offset \d+\)")


def get_rpaths(filename):
    # type: (Text) -> Tuple[Text, ...]
    """ Return a tuple of rpaths from the library `filename`.

    If `filename` is not a library then the returned tuple will be empty.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    rpath : tuple
        rpath paths in `filename`
    """
    try:
        lines = _cmd_out_err(['otool', '-l', filename])
    except RuntimeError:
        return ()
    if not _line0_says_object(lines[0], filename):
        return ()
    lines = [line.strip() for line in lines]
    paths = []
    line_no = 1
    while line_no < len(lines):
        line = lines[line_no]
        line_no += 1
        if line != 'cmd LC_RPATH':
            continue
        cmdsize, path = lines[line_no:line_no+2]
        assert cmdsize.startswith('cmdsize ')
        match = RPATH_RE.match(path)
        assert match
        paths.append(match.groups()[0])
        line_no += 2
    return tuple(paths)


def get_environment_variable_paths():
    # type: () -> Tuple[Text, ...]
    """ Return a tuple of entries in `DYLD_LIBRARY_PATH` and
    `DYLD_FALLBACK_LIBRARY_PATH`.

    This will allow us to search those locations for dependencies of libraries
    as well as `@rpath` entries.

    Returns
    -------
    env_var_paths : tuple
        path entries in environment variables
    """
    # We'll search the extra library paths in a specific order:
    # DYLD_LIBRARY_PATH and then DYLD_FALLBACK_LIBRARY_PATH
    env_var_paths = []
    extra_paths = ['DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH']
    for pathname in extra_paths:
        path_contents = os.environ.get(pathname)
        if path_contents is not None:
            for path in path_contents.split(':'):
                env_var_paths.append(path)
    return tuple(env_var_paths)


@ensure_writable
def add_rpath(filename, newpath):
    # type: (Text, Text) -> None
    """ Add rpath `newpath` to library `filename`

    Parameters
    ----------
    filename : str
        filename of library
    newpath : str
        rpath to add
    """
    check_call(['install_name_tool', '-add_rpath', newpath, filename])


def zip2dir(zip_fname, out_dir):
    # type: (Text, Text) -> None
    """ Extract `zip_fname` into output directory `out_dir`

    Parameters
    ----------
    zip_fname : str
        Filename of zip archive to write
    out_dir : str
        Directory path containing files to go in the zip archive
    """
    # Use unzip command rather than zipfile module to preserve permissions
    # http://bugs.python.org/issue15795
    check_call(['unzip', '-o', '-d', out_dir, zip_fname])


def dir2zip(in_dir, zip_fname):
    # type: (Text, Text) -> None
    """ Make a zip file `zip_fname` with contents of directory `in_dir`

    The recorded filenames are relative to `in_dir`, so doing a standard zip
    unpack of the resulting `zip_fname` in an empty directory will result in
    the original directory contents.

    Parameters
    ----------
    in_dir : str
        Directory path containing files to go in the zip archive
    zip_fname : str
        Filename of zip archive to write
    """
    z = zipfile.ZipFile(zip_fname, 'w',
                        compression=zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(in_dir):
        for file in files:
            in_fname = pjoin(root, file)
            in_stat = os.stat(in_fname)
            # Preserve file permissions, but allow copy
            info = zipfile.ZipInfo(in_fname)
            info.filename = relpath(in_fname, in_dir)
            if os.path.sep == '\\':
                # Make the path unix friendly on windows.
                # PyPI won't accept wheels with windows path separators
                info.filename = relpath(in_fname, in_dir).replace('\\', '/')
            # Set time from modification time
            info.date_time = time.localtime(in_stat.st_mtime)  # type: ignore
            # See https://stackoverflow.com/questions/434641/how-do-i-set-permissions-attributes-on-a-file-in-a-zip-file-using-pythons-zip/48435482#48435482 # noqa: E501
            # Also set regular file permissions
            perms = stat.S_IMODE(in_stat.st_mode) | stat.S_IFREG
            info.external_attr = perms << 16
            with open_readable(in_fname, 'rb') as fobj:
                contents = fobj.read()
            z.writestr(info, contents, zipfile.ZIP_DEFLATED)
    z.close()


def find_package_dirs(root_path):
    # type: (Text) -> Set[Text]
    """ Find python package directories in directory `root_path`

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
        fname = entry if root_path == '.' else pjoin(root_path, entry)
        if isdir(fname) and exists(pjoin(fname, '__init__.py')):
            package_sdirs.add(fname)
    return package_sdirs


def cmp_contents(filename1, filename2):
    # type: (Text, Text) -> bool
    """ Returns True if contents of the files are the same

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
    with open_readable(filename1, 'rb') as fobj:
        contents1 = fobj.read()
    with open_readable(filename2, 'rb') as fobj:
        contents2 = fobj.read()
    return contents1 == contents2


def get_archs(libname):
    # type: (Text) -> FrozenSet[Text]
    """ Return architecture types from library `libname`

    Parameters
    ----------
    libname : str
        filename of binary for which to return arch codes

    Returns
    -------
    arch_names : frozenset
        Empty (frozen)set if no arch codes.  If not empty, contains one or more
        of 'ppc', 'ppc64', 'i386', 'x86_64'
    """
    if not exists(libname):
        raise RuntimeError(libname + " is not a file")
    try:
        stdout = check_call(['lipo', '-info', libname])
    except RuntimeError:
        return frozenset()
    lines = [line.strip() for line in stdout.split('\n') if line.strip()]
    # For some reason, output from lipo -info on .a file generates this line
    if lines[0] == "input file {0} is not a fat file".format(libname):
        line = lines[1]
    else:
        assert len(lines) == 1
        line = lines[0]
    for reggie in (
        'Non-fat file: {0} is architecture: (.*)'.format(re.escape(libname)),
        'Architectures in the fat file: {0} are: (.*)'.format(
                                                            re.escape(libname))
    ):
        match = re.match(reggie, line)
        if match is not None:
            return frozenset(match.groups()[0].split(' '))
    raise ValueError("Unexpected output: '{0}' for {1}".format(
        stdout, libname))


def lipo_fuse(in_fname1, in_fname2, out_fname):
    # type: (Text, Text, Text) -> Text
    """ Use lipo to merge libs `filename1`, `filename2`, store in `out_fname`

    Parameters
    ----------
    in_fname1 : str
        filename of library
    in_fname2 : str
        filename of library
    out_fname : str
        filename to which to write new fused library
    """
    return check_call(
        ['lipo', '-create', in_fname1, in_fname2, '-output', out_fname])


@ensure_writable
def replace_signature(filename, identity):
    # type: (Text, Text) -> None
    """ Replace the signature of a binary file using `identity`

    See the codesign documentation for more info

    Parameters
    ----------
    filename : str
        Filepath to a binary file.
    identity : str
        The signing identity to use.
    """
    check_call(['codesign', '--force', '--sign', identity, filename])


def validate_signature(filename):
    # type: (Text) -> None
    """ Remove invalid signatures from a binary file

    If the file signature is missing or valid then it will be ignored

    Invalid signatures are replaced with an ad-hoc signature.  This is the
    closest you can get to removing a signature on MacOS

    Parameters
    ----------
    filename : str
        Filepath to a binary file
    """
    _, out, err = run_call(['codesign', '--verify', filename])
    if not err:
        return  # The existing signature is valid
    if 'code object is not signed at all' in err:
        return  # File has no signature, and adding a new one isn't necessary

    # This file's signature is invalid and needs to be replaced
    replace_signature(filename, '-')  # Replace with an ad-hoc signature

""" Tools for getting and setting install names """

from subprocess import Popen, PIPE

import os
from os.path import join as pjoin, relpath, isdir, exists
import zipfile
import re
import stat
import time


class InstallNameError(Exception):
    pass


def back_tick(cmd, ret_err=False, as_str=True, raise_err=None):
    """ Run command `cmd`, return stdout, or stdout, stderr if `ret_err`

    Roughly equivalent to ``check_output`` in Python 2.7

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
    """
    if raise_err is None:
        raise_err = False if ret_err else True
    cmd_is_seq = isinstance(cmd, (list, tuple))
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=not cmd_is_seq)
    out, err = proc.communicate()
    retcode = proc.returncode
    cmd_str = ' '.join(cmd) if cmd_is_seq else cmd
    if retcode is None:
        proc.terminate()
        raise RuntimeError(cmd_str + ' process did not terminate')
    if raise_err and retcode != 0:
        raise RuntimeError('{0} returned code {1} with error {2}'.format(
                           cmd_str, retcode, err.decode('latin-1')))
    out = out.strip()
    if as_str:
        out = out.decode('latin-1')
    if not ret_err:
        return out
    err = err.strip()
    if as_str:
        err = err.decode('latin-1')
    return out, err


def unique_by_index(sequence):
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
    # Permissions relevant to chmod
    return stat.S_IMODE(os.stat(fname).st_mode)


def ensure_permissions(mode_flags=stat.S_IWUSR):
    """decorator to ensure a filename has given permissions.

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
IN_RE = re.compile(r"(.*) \(compatibility version (\d+\.\d+\.\d+), "
                   r"current version (\d+\.\d+\.\d+)(?:, \w+)?\)")


def parse_install_name(line):
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
    return IN_RE.match(line).groups()


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
]


def _cmd_out_err(cmd):
    # Run command, return stdout or stderr if stdout is empty
    out, err = back_tick(cmd, ret_err=True)
    out = err if not len(out) else out
    return out.split('\n')


def _line0_says_object(line0, filename):
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
    back_tick(['install_name_tool', '-change', oldname, newname, filename])


@ensure_writable
def set_install_id(filename, install_id):
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
    back_tick(['install_name_tool', '-id', install_id, filename])


RPATH_RE = re.compile(r"path (.*) \(offset \d+\)")


def get_rpaths(filename):
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
        paths.append(RPATH_RE.match(path).groups()[0])
        line_no += 2
    return tuple(paths)


def get_environment_variable_paths():
    """ Return a tuple of entries in `DYLD_LIBRARY_PATH` and
    `DYLD_FALLBACK_LIBRARY_PATH`.

    This will allow us to search those locations for dependencies of libraries as
    well as `@rpath` entries.

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
    """ Add rpath `newpath` to library `filename`

    Parameters
    ----------
    filename : str
        filename of library
    newpath : str
        rpath to add
    """
    back_tick(['install_name_tool', '-add_rpath', newpath, filename])


def zip2dir(zip_fname, out_dir):
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
    back_tick(['unzip', '-o', '-d', out_dir, zip_fname])


def dir2zip(in_dir, zip_fname):
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
            info.date_time = time.localtime(in_stat.st_mtime)
            # See https://stackoverflow.com/questions/434641/how-do-i-set-permissions-attributes-on-a-file-in-a-zip-file-using-pythons-zip/48435482#48435482 # noqa: E501
            # Also set regular file permissions
            perms = stat.S_IMODE(in_stat.st_mode) | stat.S_IFREG
            info.external_attr = perms << 16
            with open_readable(in_fname, 'rb') as fobj:
                contents = fobj.read()
            z.writestr(info, contents, zipfile.ZIP_DEFLATED)
    z.close()


def find_package_dirs(root_path):
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
        stdout = back_tick(['lipo', '-info', libname])
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
            'Non-fat file: {0} is architecture: (.*)'.format(libname),
            'Architectures in the fat file: {0} are: (.*)'.format(libname)):
        reggie = re.compile(reggie)
        match = reggie.match(line)
        if match is not None:
            return frozenset(match.groups()[0].split(' '))
    raise ValueError("Unexpected output: '{0}' for {1}".format(
        stdout, libname))


def lipo_fuse(in_fname1, in_fname2, out_fname):
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
    return back_tick(['lipo', '-create',
                      in_fname1, in_fname2,
                      '-output', out_fname])


@ensure_writable
def replace_signature(filename, identity):
    """ Replace the signature of a binary file using `identity`

    See the codesign documentation for more info

    Parameters
    ----------
    filename : str
        Filepath to a binary file.
    identity : str
        The signing identity to use.
    """
    back_tick(['codesign', '--force', '--sign', identity, filename],
              raise_err=True)


def validate_signature(filename):
    """ Remove invalid signatures from a binary file

    If the file signature is missing or valid then it will be ignored

    Invalid signatures are replaced with an ad-hoc signature.  This is the
    closest you can get to removing a signature on MacOS

    Parameters
    ----------
    filename : str
        Filepath to a binary file
    """
    out, err = back_tick(['codesign', '--verify', filename],
                         ret_err=True, as_str=True, raise_err=False)
    if not err:
        return  # The existing signature is valid
    if 'code object is not signed at all' in err:
        return  # File has no signature, and adding a new one isn't necessary

    # This file's signature is invalid and needs to be replaced
    replace_signature(filename, '-')  # Replace with an ad-hoc signature

""" Tools for getting and setting install names """

from os.path import exists
import re

from wheeltools.tools import (
    back_tick,
    ensure_writable,
    find_package_dirs,
    dir2zip,
    zip2dir,
    cmp_contents,
    open_readable,
    open_rw,
    chmod_perms,
)


class InstallNameError(Exception):
    pass


IN_RE = re.compile(r"(.*) \(compatibility version (\d+\.\d+\.\d+), "
                   r"current version (\d+\.\d+\.\d+)\)")

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
    lambda s : 'is not an object file' in s,
    # cctools-862 (.ico)
    lambda s : 'The end of the file was unexpectedly encountered' in s,
    # cctools-895
    lambda s : 'The file was not recognized as a valid object file' in s,
    # 895 binary file
    lambda s: 'Invalid data was encountered while parsing the file' in s,
    # cctools-900
    lambda s : 'Object is not a Mach-O file type' in s,
    # File may not have read permissions
    lambda s : RE_PERM_DEN.search(s) is not None
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
    if not install_id is None:
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
    """ Return a tuple of rpaths from the library `filename`

    If `filename` is not a library then the returned tuple will be empty.

    Parameters
    ----------
    filaname : str
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
        if not match is None:
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
        return # The existing signature is valid
    if 'code object is not signed at all' in err:
        return # File has no signature, and adding a new one isn't necessary

    # This file's signature is invalid and needs to be replaced
    replace_signature(filename, '-') # Replace with an ad-hoc signature

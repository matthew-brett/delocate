""" Tools for getting and setting install names """

from subprocess import Popen, PIPE

import os
from os.path import join as pjoin

import re
import stat


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


def ensure_writable(f):
    """decorator to ensure a filename is writable before modifying it

    If changed, original permissions are restored after the decorated modification.
    """
    def modify(filename, *args, **kwargs):
        m = os.stat(filename).st_mode
        if not m & stat.S_IWUSR:
            os.chmod(filename, m | stat.S_IWUSR)
        try:
            return f(filename, *args, **kwargs)
        finally:
            # restore original permissions
            if not m & stat.S_IWUSR:
                os.chmod(filename, m)

    return modify


IN_RE = re.compile("(.*) \(compatibility version (\d+\.\d+\.\d+), "
                   "current version (\d+\.\d+\.\d+)\)")

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


def _line0_says_object(line0, filename):
    line0 = line0.strip()
    if line0.startswith('Archive :'):
        # nothing to do for static libs
        return False
    if not line0.startswith(filename + ':'):
        raise RuntimeError('Unexpected first line: ' + line0)
    further_report = line0[len(filename) + 1:]
    if further_report == '':
        return True
    if further_report == ' is not an object file':
        return False
    raise RuntimeError(
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
    out = back_tick(['otool', '-L', filename])
    lines = out.split('\n')
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
    out = back_tick(['otool', '-D', filename])
    lines = out.split('\n')
    if not _line0_says_object(lines[0], filename):
        return None
    if len(lines) == 1:
        return None
    if len(lines) != 2:
        raise RuntimeError('Unexpected otool output ' + out)
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
        raise RuntimeError('{0} not in install names for {1}'.format(
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
        raise RuntimeError('{0} has no install id'.format(filename))
    back_tick(['install_name_tool', '-id', install_id, filename])


RPATH_RE = re.compile("path (.*) \(offset \d+\)")

def get_rpaths(filename):
    """ Return rpaths from library `filename`

    Parameters
    ----------
    filaname : str
        filename of library

    Returns
    -------
    rpath : tuple
        rpath paths in `filename`
    """
    out = back_tick(['otool', '-l', filename])
    lines = [line.strip() for line in out.split('\n')]
    assert lines[0] == filename + ':'
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
        dictionary with (key, value) pairs of (install name, set of files in
        tree with install name)
    """
    lib_dict = {}
    for dirpath, dirnames, basenames in os.walk(start_path):
        for base in basenames:
            fname = pjoin(dirpath, base)
            if not filt_func is None and not filt_func(fname):
                continue
            for install_name in get_install_names(fname):
                if install_name in lib_dict:
                    lib_dict[install_name].add(fname)
                else:
                    lib_dict[install_name] = set([fname])
    return lib_dict

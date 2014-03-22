# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
""" Test scripts

If we appear to be running from the development directory, use the scripts in
the top-level folder ``scripts``.  Otherwise try and get the scripts from the
path
"""
from __future__ import division, print_function, absolute_import

import sys
import os
import shutil

from os.path import (dirname, join as pjoin, isfile, isdir, abspath, realpath,
                     pathsep)

from subprocess import Popen, PIPE

from nose.tools import assert_true, assert_false, assert_equal

from ..tmpdirs import InTemporaryDirectory
from ..pycompat import string_types
from ..tools import back_tick, set_install_name

from .test_delocate import EXT_LIBS, _make_libtree, _copy_to

DEBUG_PRINT = os.environ.get('DELOCATE_DEBUG_PRINT', False)

DATA_PATH = abspath(pjoin(dirname(__file__), 'data'))

def local_script_dir(script_sdir):
    # Check for presence of scripts in development directory.  ``realpath``
    # checks for the situation where the development directory has been linked
    # into the path.
    below_us_2 = realpath(pjoin(dirname(__file__), '..', '..'))
    devel_script_dir = pjoin(below_us_2, script_sdir)
    if isfile(pjoin(below_us_2, 'setup.py')) and isdir(devel_script_dir):
        return devel_script_dir
    return None

LOCAL_SCRIPT_DIR = local_script_dir('scripts')

def local_module_dir(module_name):
    mod = __import__(module_name)
    containing_path = dirname(dirname(realpath(mod.__file__)))
    if containing_path == realpath(os.getcwd()):
        return containing_path
    return None

LOCAL_MODULE_DIR = local_module_dir('delocate')


def run_command(cmd, check_code=True):
    """ Run command sequence `cmd` returning exit code, stdout, stderr

    Parameters
    ----------
    cmd : str or sequence
        string with command name or sequence of strings defining command
    check_code : {True, False}, optional
        If True, raise error for non-zero return code

    Returns
    -------
    returncode : int
        return code from execution of `cmd`
    stdout : bytes (python 3) or str (python 2)
        stdout from `cmd`
    stderr : bytes (python 3) or str (python 2)
        stderr from `cmd`
    """
    if isinstance(cmd, string_types):
        cmd = [cmd]
    else:
        cmd = list(cmd)
    if os.name == 'nt': # Need .bat file extension for windows
        cmd[0] += '.bat'
    if not LOCAL_SCRIPT_DIR is None:
        # Windows can't run script files without extensions natively so we need
        # to run local scripts (no extensions) via the Python interpreter.  On
        # Unix, we might have the wrong incantation for the Python interpreter
        # in the hash bang first line in the source file.  So, either way, run
        # the script through the Python interpreter
        cmd = [sys.executable, pjoin(LOCAL_SCRIPT_DIR, cmd[0])] + cmd[1:]
    if DEBUG_PRINT:
        print("Running command '%s'" % cmd)
    env = os.environ
    if not LOCAL_MODULE_DIR is None:
        # module likely comes from the current working directory. We might need
        # that directory on the path if we're running the scripts from a
        # temporary directory
        env = env.copy()
        pypath = env.get('PYTHONPATH', None)
        if pypath is None:
            env['PYTHONPATH'] = LOCAL_MODULE_DIR
        else:
            env['PYTHONPATH'] = LOCAL_MODULE_DIR + pathsep + pypath
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, env=env)
    stdout, stderr = proc.communicate()
    if proc.poll() == None:
        proc.terminate()
    if check_code and proc.returncode != 0:
        raise RuntimeError(
            """Command "{0}" failed with
            stdout
            ------
            {1}
            stderr
            ------
            {2}
            """.format(cmd, stdout, stderr))
    return proc.returncode, stdout, stderr


def test_listdeps():
    # smokey tests of list dependencies command
    code, stdout, stderr = run_command(['delocate-listdeps', DATA_PATH])
    lines = stdout.split('\n')
    assert_true(len(lines) >= 6)
    assert_true(set(EXT_LIBS) <= set(lines))
    assert_equal(code, 0)


def test_path():
    # Test path cleaning
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        liba, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree'))
        # Check it fixes up correctly
        code, stdout, stderr = run_command(
            ['delocate-path', 'subtree', '-L', 'deplibs'])
        assert_equal(len(os.listdir('deplibs')), 0)
        back_tick([test_lib])
        back_tick([stest_lib])
        # Make a fake external library to link to
        os.makedirs('fakelibs')
        fake_lib = realpath(_copy_to(liba, 'fakelibs', 'libfake.dylib'))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree2'))
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # Check fake libary gets copied and delocated
        out_path = pjoin('subtree2', '.dylibs')
        code, stdout, stderr = run_command(['delocate-path', 'subtree2'])
        assert_equal(os.listdir(out_path), ['libfake.dylib'])

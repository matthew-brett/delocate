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
from os.path import (dirname, join as pjoin, isfile, isdir, abspath, realpath,
                     pathsep, basename, exists)
import shutil

from subprocess import Popen, PIPE

from ..tmpdirs import InTemporaryDirectory
from ..pycompat import string_types
from ..tools import back_tick, set_install_name, zip2dir, dir2zip

from nose.tools import assert_true, assert_false, assert_equal

from .test_install_names import EXT_LIBS
from .test_delocating import _make_libtree, _copy_to
from .test_wheelies import (_fixed_wheel, PLAT_WHEEL, PURE_WHEEL,
                            STRAY_LIB_DEP)
from .test_fuse import assert_same_tree

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


def _proc_lines(in_str):
    lines = in_str.decode('latin1').split('\n') # bytes in py3
    return [line.strip() for line in lines if line.strip() != '']


def test_listdeps():
    # smokey tests of list dependencies command
    local_libs = set(['liba.dylib', 'libb.dylib', 'libc.dylib'])
    # single path, with libs
    code, stdout, stderr = run_command(['delocate-listdeps', DATA_PATH])
    assert_equal(set(_proc_lines(stdout)), local_libs)
    assert_equal(code, 0)
    # single path, no libs
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, 'pure')
        code, stdout, stderr = run_command(['delocate-listdeps', 'pure'])
        assert_equal(set(_proc_lines(stdout)), set())
        assert_equal(code, 0)
        # Multiple paths one with libs
        zip2dir(PLAT_WHEEL, 'plat')
        code, stdout, stderr = run_command(
            ['delocate-listdeps', 'pure', 'plat'])
        assert_equal(_proc_lines(stdout),
                    ['pure:', 'plat:', STRAY_LIB_DEP])
        assert_equal(code, 0)
        # With -d flag, get list of dependending modules
        code, stdout, stderr = run_command(
            ['delocate-listdeps', '-d', 'pure', 'plat'])
        assert_equal(_proc_lines(stdout),
                     ['pure:', 'plat:', STRAY_LIB_DEP + ':',
                      pjoin('plat', 'fakepkg1', 'subpkg', 'module2.so')])
        assert_equal(code, 0)
    # With --all flag, get all dependencies
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--all', DATA_PATH])
    rp_ext_libs = set(realpath(L) for L in EXT_LIBS)
    assert_equal(set(_proc_lines(stdout)), local_libs | rp_ext_libs)
    assert_equal(code, 0)
    # Works on wheels as well
    code, stdout, stderr = run_command(
        ['delocate-listdeps', PURE_WHEEL])
    assert_equal(set(_proc_lines(stdout)), set())
    code, stdout, stderr = run_command(
        ['delocate-listdeps', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(_proc_lines(stdout),
                 [PURE_WHEEL + ':', PLAT_WHEEL + ':', STRAY_LIB_DEP])
    # -d flag (is also --dependency flag)
    m2 = pjoin('fakepkg1', 'subpkg', 'module2.so')
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--depending', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(_proc_lines(stdout),
                 [PURE_WHEEL + ':', PLAT_WHEEL + ':', STRAY_LIB_DEP + ':',
                  m2])
    # Can be used with --all
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--all', '--depending', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(_proc_lines(stdout),
                 [PURE_WHEEL + ':', PLAT_WHEEL + ':',
                  STRAY_LIB_DEP + ':', m2,
                  EXT_LIBS[1] + ':', m2])


def test_path():
    # Test path cleaning
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        liba, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree'))
        os.makedirs('fakelibs')
        # Make a fake external library to link to
        fake_lib = realpath(_copy_to(liba, 'fakelibs', 'libfake.dylib'))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree2'))
        back_tick([test_lib])
        back_tick([stest_lib])
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # Check it fixes up correctly
        code, stdout, stderr = run_command(
            ['delocate-path', 'subtree', 'subtree2', '-L', 'deplibs'])
        assert_equal(len(os.listdir(pjoin('subtree', 'deplibs'))), 0)
        # Check fake libary gets copied and delocated
        out_path = pjoin('subtree2', 'deplibs')
        assert_equal(os.listdir(out_path), ['libfake.dylib'])


def _check_wheel(wheel_fname, lib_sdir):
    wheel_fname = abspath(wheel_fname)
    with InTemporaryDirectory():
        zip2dir(wheel_fname, 'plat_pkg')
        dylibs = pjoin('plat_pkg', 'fakepkg1', lib_sdir)
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])


def test_wheel():
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(
            ['delocate-wheel', fixed_wheel])
        _check_wheel(fixed_wheel, '.dylibs')
        # Make another copy to test another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-L', 'dynlibs_dir', fixed_wheel])
        _check_wheel(fixed_wheel, 'dynlibs_dir')
        # Another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-w', 'fixed', fixed_wheel])
        _check_wheel(pjoin('fixed', basename(fixed_wheel)), '.dylibs')
        # More than one wheel
        shutil.copy2(fixed_wheel, 'wheel_copy.ext')
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-w', 'fixed2', fixed_wheel, 'wheel_copy.ext'])
        assert_equal(_proc_lines(stdout),
                     ['Fixing: ' + name
                      for name in (fixed_wheel, 'wheel_copy.ext')])
        _check_wheel(pjoin('fixed2', basename(fixed_wheel)), '.dylibs')
        _check_wheel(pjoin('fixed2', 'wheel_copy.ext'), '.dylibs')
        # Verbose - single wheel
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-w', 'fixed3', fixed_wheel, '-v'])
        _check_wheel(pjoin('fixed3', basename(fixed_wheel)), '.dylibs')
        wheel_lines1 = ['Fixing: ' + fixed_wheel,
                        'Copied to package .dylibs directory:',
                        stray_lib]
        assert_equal(_proc_lines(stdout), wheel_lines1)
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-v', '--wheel-dir', 'fixed4',
             fixed_wheel, 'wheel_copy.ext'])
        wheel_lines2 = ['Fixing: wheel_copy.ext',
                        'Copied to package .dylibs directory:',
                        stray_lib]
        assert_equal(_proc_lines(stdout), wheel_lines1 + wheel_lines2)


def test_fuse_wheels():
    # Some tests for wheel fusing
    with InTemporaryDirectory():
        zip2dir(PLAT_WHEEL, 'to_wheel')
        zip2dir(PLAT_WHEEL, 'from_wheel')
        dir2zip('to_wheel', 'to_wheel.whl')
        dir2zip('from_wheel', 'from_wheel.whl')
        code, stdout, stderr = run_command(
            ['delocate-fuse', 'to_wheel.whl', 'from_wheel.whl'])
        assert_equal(code, 0)
        zip2dir('to_wheel.whl', 'to_wheel_fused')
        assert_same_tree('to_wheel_fused', 'from_wheel')
        # Test output argument
        os.mkdir('wheels')
        code, stdout, stderr = run_command(
            ['delocate-fuse', 'to_wheel.whl', 'from_wheel.whl',
             '-w', 'wheels'])
        zip2dir(pjoin('wheels', 'to_wheel.whl'), 'to_wheel_refused')
        assert_same_tree('to_wheel_refused', 'from_wheel')

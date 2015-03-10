# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
""" Test scripts

If we appear to be running from the development directory, use the scripts in
the top-level folder ``scripts``.  Otherwise try and get the scripts from the
path
"""
from __future__ import division, print_function, absolute_import

import os
from os.path import (dirname, join as pjoin, isfile, abspath, realpath,
                     basename, exists)
import shutil

from ..tmpdirs import InTemporaryDirectory
from ..tools import back_tick, set_install_name, zip2dir, dir2zip
from ..wheeltools import InWheel
from .scriptrunner import ScriptRunner

from nose.tools import (assert_true, assert_false, assert_equal, assert_raises,
                        assert_not_equal)

from .test_install_names import EXT_LIBS
from .test_delocating import _make_libtree, _copy_to, _make_bare_depends
from .test_wheelies import (_fixed_wheel, PLAT_WHEEL, PURE_WHEEL,
                            STRAY_LIB_DEP, WHEEL_PATCH, WHEEL_PATCH_BAD,
                            _thin_lib, _thin_mod, _rename_module)
from .test_fuse import assert_same_tree
from .test_wheeltools import get_winfo


def _proc_lines(in_str):
    """ Decode `in_string` to str, split lines, strip whitespace

    Remove any empty lines.

    Parameters
    ----------
    in_str : bytes
        Input bytes for splitting, stripping

    Returns
    -------
    out_lines : list
        List of line ``str`` where each line has been stripped of leading and
        trailing whitespace and empty lines have been removed.
    """
    lines = in_str.decode('latin1').splitlines()
    return [line.strip() for line in lines if line.strip() != '']


lines_runner = ScriptRunner(output_processor = _proc_lines)
run_command = lines_runner.run_command
bytes_runner = ScriptRunner()


DATA_PATH = abspath(pjoin(dirname(__file__), 'data'))

def test_listdeps():
    # smokey tests of list dependencies command
    local_libs = set(['liba.dylib', 'libb.dylib', 'libc.dylib'])
    # single path, with libs
    code, stdout, stderr = run_command(['delocate-listdeps', DATA_PATH])
    assert_equal(set(stdout), local_libs)
    assert_equal(code, 0)
    # single path, no libs
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, 'pure')
        code, stdout, stderr = run_command(['delocate-listdeps', 'pure'])
        assert_equal(set(stdout), set())
        assert_equal(code, 0)
        # Multiple paths one with libs
        zip2dir(PLAT_WHEEL, 'plat')
        code, stdout, stderr = run_command(
            ['delocate-listdeps', 'pure', 'plat'])
        assert_equal(stdout,
                    ['pure:', 'plat:', STRAY_LIB_DEP])
        assert_equal(code, 0)
        # With -d flag, get list of dependending modules
        code, stdout, stderr = run_command(
            ['delocate-listdeps', '-d', 'pure', 'plat'])
        assert_equal(stdout,
                     ['pure:', 'plat:', STRAY_LIB_DEP + ':',
                      pjoin('plat', 'fakepkg1', 'subpkg', 'module2.so')])
        assert_equal(code, 0)
    # With --all flag, get all dependencies
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--all', DATA_PATH])
    rp_ext_libs = set(realpath(L) for L in EXT_LIBS)
    assert_equal(set(stdout), local_libs | rp_ext_libs)
    assert_equal(code, 0)
    # Works on wheels as well
    code, stdout, stderr = run_command(
        ['delocate-listdeps', PURE_WHEEL])
    assert_equal(set(stdout), set())
    code, stdout, stderr = run_command(
        ['delocate-listdeps', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(stdout,
                 [PURE_WHEEL + ':', PLAT_WHEEL + ':', STRAY_LIB_DEP])
    # -d flag (is also --dependency flag)
    m2 = pjoin('fakepkg1', 'subpkg', 'module2.so')
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--depending', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(stdout,
                 [PURE_WHEEL + ':', PLAT_WHEEL + ':', STRAY_LIB_DEP + ':',
                  m2])
    # Can be used with --all
    code, stdout, stderr = run_command(
        ['delocate-listdeps', '--all', '--depending', PURE_WHEEL, PLAT_WHEEL])
    assert_equal(stdout,
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


def test_path_dylibs():
    # Test delocate-path with and without dylib extensions
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        out_dypath = pjoin('subtree', 'deplibs')
        code, stdout, stderr = run_command(
            ['delocate-path', 'subtree', '-L', 'deplibs', '-d'])
        assert_equal(len(os.listdir(out_dypath)), 0)
        code, stdout, stderr = run_command(
            ['delocate-path', 'subtree', '-L', 'deplibs', '--dylibs-only'])
        assert_equal(len(os.listdir(pjoin('subtree', 'deplibs'))), 0)
        # Default - does inspect non-dylib files
        code, stdout, stderr = run_command(
            ['delocate-path', 'subtree', '-L', 'deplibs'])
        assert_equal(os.listdir(out_dypath), ['liba.dylib'])


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
        assert_equal(stdout,
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
        assert_equal(stdout, wheel_lines1)
        code, stdout, stderr = run_command(
            ['delocate-wheel', '-v', '--wheel-dir', 'fixed4',
             fixed_wheel, 'wheel_copy.ext'])
        wheel_lines2 = ['Fixing: wheel_copy.ext',
                        'Copied to package .dylibs directory:',
                        stray_lib]
        assert_equal(stdout, wheel_lines1 + wheel_lines2)


def test_fix_wheel_dylibs():
    # Check default and non-default search for dynamic libraries
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, 'module.other', 'test.whl')
        shutil.copyfile('test.whl', 'test2.whl')
        # Default is to look in all files and therefore fix
        code, stdout, stderr = run_command(
            ['delocate-wheel', 'test.whl'])
        _check_wheel('test.whl', '.dylibs')
        # Can turn this off to only look in dynamic lib exts
        code, stdout, stderr = run_command(
            ['delocate-wheel', 'test2.whl', '-d'])
        with InWheel('test2.whl'):  # No fix
            assert_false(exists(pjoin('fakepkg1', '.dylibs')))


def test_fix_wheel_archs():
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Test check of architectures
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        # Fixed wheel, architectures are OK
        code, stdout, stderr = run_command(
            ['delocate-wheel', fixed_wheel, '-k'])
        _check_wheel(fixed_wheel, '.dylibs')
        # Broken with one architecture removed still OK without checking
        # But if we check, raise error
        fmt_str = 'Fixing: {0}\n{1} needs arch {2} missing from {3}'
        archs = set(('x86_64', 'i386'))
        def _fix_break(arch):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
        def _fix_break_fix(arch):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
            _thin_mod(fixed_wheel, arch)
        for arch in archs:
            # Not checked
            _fix_break(arch)
            code, stdout, stderr = run_command(
                ['delocate-wheel', fixed_wheel])
            _check_wheel(fixed_wheel, '.dylibs')
            # Checked
            _fix_break(arch)
            code, stdout, stderr = bytes_runner.run_command(
                ['delocate-wheel', fixed_wheel, '--check-archs'],
                check_code=False)
            assert_false(code == 0)
            stderr = stderr.decode('latin1').strip()
            assert_true(stderr.startswith('Traceback'))
            assert_true(stderr.endswith(
                "Some missing architectures in wheel"))
            assert_equal(stdout.strip(), b'')
            # Checked, verbose
            _fix_break(arch)
            code, stdout, stderr = bytes_runner.run_command(
                ['delocate-wheel', fixed_wheel, '--check-archs', '-v'],
                check_code=False)
            assert_false(code == 0)
            stderr = stderr.decode('latin1').strip()
            assert_true(stderr.startswith('Traceback'))
            assert_true(stderr.endswith(
                "Some missing architectures in wheel"))
            stdout = stdout.decode('latin1').strip()
            assert_equal(stdout,
                         fmt_str.format(
                             fixed_wheel,
                             'fakepkg1/subpkg/module2.so',
                             archs.difference([arch]).pop(),
                             stray_lib))
            # Require particular architectures
        both_archs = 'i386,x86_64'
        for ok in ('intel', 'i386', 'x86_64', both_archs):
            _fixed_wheel(tmpdir)
            code, stdout, stderr = run_command(
                ['delocate-wheel', fixed_wheel, '--require-archs=' + ok])
        for arch in archs:
            other_arch = archs.difference([arch]).pop()
            for not_ok in ('intel', both_archs, other_arch):
                _fix_break_fix(arch)
                code, stdout, stderr = run_command(
                    ['delocate-wheel', fixed_wheel,
                     '--require-archs=' + not_ok],
                check_code=False)
                assert_false(code == 0)


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


def test_patch_wheel():
    # Some tests for patching wheel
    with InTemporaryDirectory():
        shutil.copyfile(PURE_WHEEL, 'example.whl')
        # Default is to overwrite input
        code, stdout, stderr = run_command(
            ['delocate-patch', 'example.whl', WHEEL_PATCH])
        zip2dir('example.whl', 'wheel1')
        with open(pjoin('wheel1', 'fakepkg2', '__init__.py'), 'rt') as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Pass output directory
        shutil.copyfile(PURE_WHEEL, 'example.whl')
        code, stdout, stderr = run_command(
            ['delocate-patch', 'example.whl', WHEEL_PATCH, '-w', 'wheels'])
        zip2dir(pjoin('wheels', 'example.whl'), 'wheel2')
        with open(pjoin('wheel2', 'fakepkg2', '__init__.py'), 'rt') as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Bad patch fails
        shutil.copyfile(PURE_WHEEL, 'example.whl')
        assert_raises(RuntimeError,
                      run_command,
                      ['delocate-patch', 'example.whl', WHEEL_PATCH_BAD])


def test_add_platforms():
    # Check adding platform to wheel name and tag section
    exp_items = [('Generator', 'bdist_wheel (0.23.0)'),
                 ('Root-Is-Purelib', 'false'),
                 ('Tag', 'cp27-none-macosx_10_6_intel'),
                 ('Wheel-Version', '1.0')]
    assert_equal(get_winfo(PLAT_WHEEL, drop_version=False), exp_items)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Need to specify at least one platform
        assert_raises(RuntimeError, run_command,
            ['delocate-addplat', PURE_WHEEL, '-w', tmpdir])
        plat_args = ['-p', 'macosx_10_9_intel',
                    '--plat-tag', 'macosx_10_9_x86_64']
        # Can't add platforms to a pure wheel
        assert_raises(RuntimeError, run_command,
            ['delocate-addplat', PURE_WHEEL, '-w', tmpdir] + plat_args)
        assert_false(exists(out_fname))
        # Error raised (as above) unless ``--skip-error`` flag set
        code, stdout, stderr = run_command(
            ['delocate-addplat', PURE_WHEEL, '-w', tmpdir, '-k'] + plat_args)
        # Still doesn't do anything though
        assert_false(exists(out_fname))
        # Works for plat_wheel
        out_fname = ('fakepkg1-1.0-cp27-none-macosx_10_6_intel.'
                     'macosx_10_9_intel.macosx_10_9_x86_64.whl')
        code, stdout, stderr = run_command(
            ['delocate-addplat', PLAT_WHEEL, '-w', tmpdir] + plat_args)
        assert_true(isfile(out_fname))
        # Expected output minus wheel-version (that might change)
        extra_exp = [('Generator', 'bdist_wheel (0.23.0)'),
                      ('Root-Is-Purelib', 'false'),
                      ('Tag', 'cp27-none-macosx_10_6_intel'),
                      ('Tag', 'cp27-none-macosx_10_9_intel'),
                      ('Tag', 'cp27-none-macosx_10_9_x86_64')]
        assert_equal(get_winfo(out_fname), extra_exp)
        # If wheel exists (as it does) then raise error
        assert_raises(RuntimeError, run_command,
            ['delocate-addplat', PLAT_WHEEL, '-w', tmpdir] + plat_args)
        # Unless clobber is set
        code, stdout, stderr = run_command(
            ['delocate-addplat', PLAT_WHEEL, '-c', '-w', tmpdir] + plat_args)
        # Can also specify platform tags via --osx-ver flags
        code, stdout, stderr = run_command(
            ['delocate-addplat', PLAT_WHEEL, '-c', '-w', tmpdir, '-x', '10_9'])
        assert_equal(get_winfo(out_fname), extra_exp)
        # Can mix plat_tag and osx_ver
        out_big_fname = ('fakepkg1-1.0-cp27-none-macosx_10_6_intel.'
                         'macosx_10_9_intel.macosx_10_9_x86_64.'
                         'macosx_10_10_intel.macosx_10_10_x86_64.whl')
        extra_big_exp = [('Generator', 'bdist_wheel (0.23.0)'),
                         ('Root-Is-Purelib', 'false'),
                         ('Tag', 'cp27-none-macosx_10_10_intel'),
                         ('Tag', 'cp27-none-macosx_10_10_x86_64'),
                         ('Tag', 'cp27-none-macosx_10_6_intel'),
                         ('Tag', 'cp27-none-macosx_10_9_intel'),
                         ('Tag', 'cp27-none-macosx_10_9_x86_64')]
        code, stdout, stderr = run_command(
            ['delocate-addplat', PLAT_WHEEL, '-w', tmpdir, '-x', '10_10']
            + plat_args)
        assert_equal(get_winfo(out_big_fname), extra_big_exp)
        # Default is to write into directory of wheel
        os.mkdir('wheels')
        shutil.copy2(PLAT_WHEEL, 'wheels')
        local_plat = pjoin('wheels', basename(PLAT_WHEEL))
        local_out = pjoin('wheels', out_fname)
        code, stdout, stderr = run_command(
            ['delocate-addplat', local_plat]  + plat_args)
        assert_true(exists(local_out))
        # With rm_orig flag, delete original unmodified wheel
        os.unlink(local_out)
        code, stdout, stderr = run_command(
            ['delocate-addplat', '-r', local_plat]  + plat_args)
        assert_false(exists(local_plat))
        assert_true(exists(local_out))
        # Copy original back again
        shutil.copy2(PLAT_WHEEL, 'wheels')
        # If platforms already present, don't write more
        res = sorted(os.listdir('wheels'))
        assert_equal(get_winfo(local_out), extra_exp)
        code, stdout, stderr = run_command(
            ['delocate-addplat', local_out, '--clobber']  + plat_args)
        assert_equal(sorted(os.listdir('wheels')), res)
        assert_equal(get_winfo(local_out), extra_exp)
        # The wheel doesn't get deleted output name same as input, as here
        code, stdout, stderr = run_command(
            ['delocate-addplat', local_out, '-r', '--clobber']  + plat_args)
        assert_equal(sorted(os.listdir('wheels')), res)
        # But adds WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        assert_not_equal(get_winfo(local_out), extra_exp)
        code, stdout, stderr = run_command(
            ['delocate-addplat', local_out, '--clobber']  + plat_args)
        assert_equal(sorted(os.listdir('wheels')), res)
        assert_equal(get_winfo(local_out), extra_exp)

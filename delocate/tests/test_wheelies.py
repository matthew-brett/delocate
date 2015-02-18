""" Direct tests of fixes to wheels """

import os
from os.path import (join as pjoin, basename, realpath, abspath, exists)
import shutil
from subprocess import check_call

from ..delocating import (DelocationError, delocate_wheel, patch_wheel,
                          DLC_PREFIX)
from ..tools import (get_install_names, set_install_name, zip2dir,
                     dir2zip, back_tick, get_install_id, get_archs)
from ..wheeltools import InWheel

from ..tmpdirs import InTemporaryDirectory, InGivenDirectory

from nose.tools import (assert_true, assert_false, assert_raises, assert_equal)

from .test_install_names import DATA_PATH, EXT_LIBS
from .test_tools import (ARCH_32, ARCH_BOTH)

PLAT_WHEEL = pjoin(DATA_PATH, 'fakepkg1-1.0-cp27-none-macosx_10_6_intel.whl')
PURE_WHEEL = pjoin(DATA_PATH, 'fakepkg2-1.0-py27-none-any.whl')
STRAY_LIB = pjoin(DATA_PATH, 'libextfunc.dylib')
# The install_name in the wheel for the stray library
STRAY_LIB_DEP = ('/Users/mb312/dev_trees/delocate/wheel_makers/'
                 'fakepkg1/libs/libextfunc.dylib')
WHEEL_PATCH = pjoin(DATA_PATH, 'fakepkg2.patch')
WHEEL_PATCH_BAD = pjoin(DATA_PATH, 'fakepkg2.bad_patch')


def test_fix_pure_python():
    # Test fixing a pure python package gives no change
    with InTemporaryDirectory():
        os.makedirs('wheels')
        shutil.copy2(PURE_WHEEL, 'wheels')
        wheel_name = pjoin('wheels', basename(PURE_WHEEL))
        assert_equal(delocate_wheel(wheel_name), {})
        zip2dir(wheel_name, 'pure_pkg')
        assert_true(exists(pjoin('pure_pkg', 'fakepkg2')))
        assert_false(exists(pjoin('pure_pkg', 'fakepkg2', '.dylibs')))


def _fixed_wheel(out_path):
    wheel_base = basename(PLAT_WHEEL)
    with InGivenDirectory(out_path):
        zip2dir(PLAT_WHEEL, '_plat_pkg')
        if not exists('_libs'):
            os.makedirs('_libs')
        shutil.copy2(STRAY_LIB, '_libs')
        stray_lib = pjoin(abspath(realpath('_libs')), basename(STRAY_LIB))
        requiring = pjoin('_plat_pkg', 'fakepkg1', 'subpkg', 'module2.so')
        old_lib = set(get_install_names(requiring)).difference(EXT_LIBS).pop()
        set_install_name(requiring, old_lib, stray_lib)
        dir2zip('_plat_pkg', wheel_base)
        shutil.rmtree('_plat_pkg')
    return pjoin(out_path, wheel_base), stray_lib


def _rename_module(in_wheel, mod_fname, out_wheel):
    # Rename module with library dependency in wheel
    with InWheel(in_wheel, out_wheel):
        mod_dir = pjoin('fakepkg1', 'subpkg')
        os.rename(pjoin(mod_dir, 'module2.so'), pjoin(mod_dir, mod_fname))
    return out_wheel


def test_fix_plat():
    # Can we fix a wheel with a stray library?
    # We have to make one that works first
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_true(exists(stray_lib))
        # Shortcut
        _rp = realpath
        # In-place fix
        dep_mod = pjoin('fakepkg1', 'subpkg', 'module2.so')
        assert_equal(delocate_wheel(fixed_wheel),
                     {_rp(stray_lib): {dep_mod: stray_lib}})
        zip2dir(fixed_wheel, 'plat_pkg')
        assert_true(exists(pjoin('plat_pkg', 'fakepkg1')))
        dylibs = pjoin('plat_pkg', 'fakepkg1', '.dylibs')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # New output name
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_equal(delocate_wheel(fixed_wheel, 'fixed_wheel.ext'),
                     {_rp(stray_lib): {dep_mod: stray_lib}})
        zip2dir('fixed_wheel.ext', 'plat_pkg1')
        assert_true(exists(pjoin('plat_pkg1', 'fakepkg1')))
        dylibs = pjoin('plat_pkg1', 'fakepkg1', '.dylibs')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # Test another lib output directory
        assert_equal(delocate_wheel(fixed_wheel,
                                    'fixed_wheel2.ext',
                                    'dylibs_dir'),
                     {_rp(stray_lib): {dep_mod: stray_lib}})
        zip2dir('fixed_wheel2.ext', 'plat_pkg2')
        assert_true(exists(pjoin('plat_pkg2', 'fakepkg1')))
        dylibs = pjoin('plat_pkg2', 'fakepkg1', 'dylibs_dir')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # Test check for existing output directory
        assert_raises(DelocationError,
                      delocate_wheel,
                      fixed_wheel,
                      'broken_wheel.ext',
                      'subpkg')
        # Test that `wheel unpack` works
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_equal(delocate_wheel(fixed_wheel),
                     {_rp(stray_lib): {dep_mod: stray_lib}})
        back_tick(['wheel', 'unpack', fixed_wheel])
        # Check that copied libraries have modified install_name_ids
        zip2dir(fixed_wheel, 'plat_pkg3')
        base_stray = basename(stray_lib)
        the_lib = pjoin('plat_pkg3', 'fakepkg1', '.dylibs', base_stray)
        inst_id = DLC_PREFIX + 'fakepkg1/' + base_stray
        assert_equal(get_install_id(the_lib), inst_id)


def test_fix_plat_dylibs():
    # Check default and non-default searches for dylibs
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, 'module.other', 'test.whl')
        # With dylibs-only - only analyze files with exts '.dylib', '.so'
        assert_equal(delocate_wheel('test.whl', lib_filt_func='dylibs-only'),
                     {})
        # With func that doesn't find the module
        func = lambda fn : fn.endswith('.so')
        assert_equal(delocate_wheel('test.whl', lib_filt_func=func), {})
        # Default - looks in every file
        shutil.copyfile('test.whl', 'test2.whl')  # for following test
        dep_mod = pjoin('fakepkg1', 'subpkg', 'module.other')
        assert_equal(delocate_wheel('test.whl'),
                     {realpath(stray_lib): {dep_mod: stray_lib}})
        # With func that does find the module
        func = lambda fn : fn.endswith('.other')
        assert_equal(delocate_wheel('test2.whl', lib_filt_func=func),
                     {realpath(stray_lib): {dep_mod: stray_lib}})


def _thin_lib(stray_lib, arch):
    check_call(['lipo', '-thin', arch, stray_lib, '-output', stray_lib])


def _thin_mod(wheel, arch):
    with InWheel(wheel, wheel):
        mod_fname = pjoin('fakepkg1', 'subpkg', 'module2.so')
        check_call(['lipo', '-thin', arch, mod_fname, '-output', mod_fname])


def test__thinning():
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        mod_fname = pjoin('fakepkg1', 'subpkg', 'module2.so')
        assert_equal(get_archs(stray_lib), ARCH_BOTH)
        with InWheel(fixed_wheel):
            assert_equal(get_archs(mod_fname), ARCH_BOTH)
        _thin_lib(stray_lib, 'i386')
        _thin_mod(fixed_wheel, 'i386')
        assert_equal(get_archs(stray_lib), ARCH_32)
        with InWheel(fixed_wheel):
            assert_equal(get_archs(mod_fname), ARCH_32)


def test_check_plat_archs():
    # Check flag to check architectures
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        dep_mod = pjoin('fakepkg1', 'subpkg', 'module2.so')
        # No complaint for stored / fixed wheel
        assert_equal(delocate_wheel(fixed_wheel, require_archs=()),
                     {realpath(stray_lib): {dep_mod: stray_lib}})
        # Make a new copy and break it and fix it again
        def _fix_break(arch):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
        def _fix_break_fix(arch):
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
            _thin_mod(fixed_wheel, arch)
        for arch in ('x86_64', 'i386'):
            # OK unless we check
            _fix_break(arch)
            assert_equal(
                delocate_wheel(fixed_wheel, require_archs=None),
                {realpath(stray_lib): {dep_mod: stray_lib}})
            # Now we check, and error raised
            _fix_break(arch)
            assert_raises(DelocationError, delocate_wheel, fixed_wheel,
                          require_archs=())
            # We can fix again by thinning the module too
            _fix_break_fix(arch)
            assert_equal(
                delocate_wheel(fixed_wheel, require_archs=()),
                {realpath(stray_lib): {dep_mod: stray_lib}})
            # But if we require the arch we don't have, it breaks
            for req_arch in ('intel',
                             ARCH_BOTH,
                             ARCH_BOTH.difference([arch])):
                _fix_break_fix(arch)
                assert_raises(DelocationError, delocate_wheel, fixed_wheel,
                              require_archs=req_arch)
        # Can be verbose (we won't check output though)
        _fix_break('x86_64')
        assert_raises(DelocationError, delocate_wheel, fixed_wheel,
                      require_archs=(), check_verbose=True)


def test_patch_wheel():
    # Check patching of wheel
    with InTemporaryDirectory():
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        patch_wheel(PURE_WHEEL, WHEEL_PATCH, out_fname)
        zip2dir(out_fname, 'wheel1')
        with open(pjoin('wheel1', 'fakepkg2', '__init__.py'), 'rt') as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Check that wheel unpack works
        back_tick(['wheel', 'unpack', out_fname])
        # Copy the original, check it doesn't have patch
        shutil.copyfile(PURE_WHEEL, 'copied.whl')
        zip2dir('copied.whl', 'wheel2')
        with open(pjoin('wheel2', 'fakepkg2', '__init__.py'), 'rt') as fobj:
            assert_equal(fobj.read(), '')
        # Overwrite input wheel (the default)
        patch_wheel('copied.whl', WHEEL_PATCH)
        # Patched
        zip2dir('copied.whl', 'wheel3')
        with open(pjoin('wheel3', 'fakepkg2', '__init__.py'), 'rt') as fobj:
            assert_equal(fobj.read(), 'print("Am in init")\n')
        # Check bad patch raises error
        assert_raises(RuntimeError,
                      patch_wheel, PURE_WHEEL, WHEEL_PATCH_BAD, 'out.whl')

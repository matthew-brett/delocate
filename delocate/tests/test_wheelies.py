""" Direct tests of fixes to wheels """

import os
from os.path import (join as pjoin, dirname, basename, relpath, realpath,
                     abspath, exists)
import shutil

from ..delocator import DelocationError, delocate_wheel
from ..tools import (get_install_names, set_install_name, zip2dir,
                     dir2zip)

from ..tmpdirs import InTemporaryDirectory, InGivenDirectory

from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import DATA_PATH
from .test_delocate import EXT_LIBS

PLAT_WHEEL = pjoin(DATA_PATH, 'fakepkg1-1.0-cp27-none-macosx_10_6_intel.whl')
PURE_WHEEL = pjoin(DATA_PATH, 'fakepkg2-1.0-py27-none-any.whl')
STRAY_LIB = pjoin(DATA_PATH, 'libextfunc.dylib')
# The install_name in the wheel for the stray library
STRAY_LIB_DEP = ('/Users/mb312/dev_trees/delocate/wheel_makers/'
                 'fakepkg1/libs/libextfunc.dylib')


def test_fix_pure_python():
    # Test fixing a pure python package gives no change
    with InTemporaryDirectory():
        os.makedirs('wheels')
        shutil.copy2(PURE_WHEEL, 'wheels')
        wheel_name = pjoin('wheels', basename(PURE_WHEEL))
        assert_equal(delocate_wheel(wheel_name), set())
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


def test_fix_plat():
    # Can we fix a wheel with a stray library?
    # We have to make one that works first
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_true(exists(stray_lib))
        # In-place fix
        assert_equal(delocate_wheel(fixed_wheel),
                     set([stray_lib]))
        zip2dir(fixed_wheel, 'plat_pkg')
        assert_true(exists(pjoin('plat_pkg', 'fakepkg1')))
        dylibs = pjoin('plat_pkg', 'fakepkg1', '.dylibs')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # New output name
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_equal(delocate_wheel(fixed_wheel, 'fixed_wheel.ext'),
                     set([stray_lib]))
        zip2dir('fixed_wheel.ext', 'plat_pkg1')
        assert_true(exists(pjoin('plat_pkg1', 'fakepkg1')))
        dylibs = pjoin('plat_pkg1', 'fakepkg1', '.dylibs')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # Test another lib output directory
        assert_equal(delocate_wheel(fixed_wheel,
                                    'fixed_wheel2.ext',
                                    'dylibs_dir'),
                     set([stray_lib]))
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

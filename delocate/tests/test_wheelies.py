""" Direct tests of fixes to wheels """

import os
from os.path import (join as pjoin, dirname, basename, relpath, realpath,
                     abspath, exists)
import shutil

from ..delocator import (DelocationError, delocate_wheel, zip2dir,
                         dir2zip)
from ..tools import (tree_libs, get_install_names, get_rpaths,
                     set_install_name, back_tick)

from ..tmpdirs import InTemporaryDirectory, InGivenDirectory
from nose.tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)

from .test_install_names import (DATA_PATH, LIBA, LIBB, LIBC, TEST_LIB,
                                 _copy_libs)
from .test_delocate import EXT_LIBS

PLAT_WHEEL = pjoin(DATA_PATH, 'fakepkg1-1.0-cp27-none-macosx_10_6_intel.whl')
PURE_WHEEL = pjoin(DATA_PATH, 'fakepkg2-1.0-py27-none-any.whl')
STRAY_LIB = pjoin(DATA_PATH, 'libextfunc.dylib')


def test_fix_pure_python():
    # Test fixing a pure python package gives no change
    with InTemporaryDirectory():
        os.makedirs('wheels')
        shutil.copy2(PURE_WHEEL, 'wheels')
        wheel_name = pjoin('wheels', basename(PURE_WHEEL))
        delocate_wheel(wheel_name)
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
        delocate_wheel(fixed_wheel)
        zip2dir(fixed_wheel, 'plat_pkg')
        assert_true(exists(pjoin('plat_pkg', 'fakepkg1')))
        dylibs = pjoin('plat_pkg', 'fakepkg1', '.dylibs')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # Make another copy to test another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        delocate_wheel(fixed_wheel, 'dylibs_dir')
        zip2dir(fixed_wheel, 'plat_pkg2')
        assert_true(exists(pjoin('plat_pkg2', 'fakepkg1')))
        dylibs = pjoin('plat_pkg2', 'fakepkg1', 'dylibs_dir')
        assert_true(exists(dylibs))
        assert_equal(os.listdir(dylibs), ['libextfunc.dylib'])
        # And another to test check for existing output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        assert_raises(DelocationError,
                      delocate_wheel, fixed_wheel, 'subpkg')

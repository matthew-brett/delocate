""" Tests for relocating libraries """

from __future__ import division, print_function

import os
from os.path import (join as pjoin, dirname, basename, relpath, realpath,
                     splitext)
import shutil

from ..delocating import (DelocationError, delocate_tree_libs, copy_recurse,
                          delocate_path, check_archs, bads_report)
from ..libsana import tree_libs
from ..tools import (get_install_names, set_install_name, back_tick)

from ..tmpdirs import InTemporaryDirectory

from nose.tools import (assert_true, assert_raises, assert_equal)

from .test_install_names import (LIBA, LIBB, LIBC, TEST_LIB, _copy_libs,
                                 EXT_LIBS)
from .test_tools import (LIB32, LIB64, LIB64A, LIBBOTH, ARCH_64, ARCH_32,
                         ARCH_BOTH)
from .test_libsana import get_ext_dict

def _make_libtree(out_path):
    liba, libb, libc, test_lib = _copy_libs(
        [LIBA, LIBB, LIBC, TEST_LIB], out_path)
    sub_path = pjoin(out_path, 'subsub')
    slibc, stest_lib = _copy_libs([libc, test_lib], sub_path)
    # Set execute permissions
    for exe in (test_lib, stest_lib):
        os.chmod(exe, 0o744)
    # Check test-lib doesn't work because of relative library paths
    assert_raises(RuntimeError, back_tick, [test_lib])
    assert_raises(RuntimeError, back_tick, [stest_lib])
    # Fixup the relative path library names by setting absolute paths
    for fname, using, path in (
        (libb, 'liba.dylib', out_path),
        (libc, 'liba.dylib', out_path),
        (libc, 'libb.dylib', out_path),
        (test_lib, 'libc.dylib', out_path),
        (slibc, 'liba.dylib', out_path),
        (slibc, 'libb.dylib', out_path),
        (stest_lib, 'libc.dylib', sub_path),
                        ):
        set_install_name(fname, using, pjoin(path, using))
    # Check scripts now execute correctly
    back_tick([test_lib])
    back_tick([stest_lib])
    return liba, libb, libc, test_lib, slibc, stest_lib


def test_delocate_tree_libs():
    # Test routine to copy library dependencies into a local directory
    with InTemporaryDirectory() as tmpdir:
        # Copy libs into a temporary directory
        subtree = pjoin(tmpdir, 'subtree')
        all_local_libs = _make_libtree(subtree)
        liba, libb, libc, test_lib, slibc, stest_lib = all_local_libs
        lib_dict = tree_libs(subtree)
        copy_dir = 'dynlibs'
        os.makedirs(copy_dir)
        # First check that missing library causes error
        set_install_name(liba,
                         '/usr/lib/libstdc++.6.dylib',
                         '/unlikely/libname.dylib')
        lib_dict = tree_libs(subtree)
        assert_raises(DelocationError,
                      delocate_tree_libs, lib_dict, copy_dir, subtree)
        # fix it
        set_install_name(liba,
                         '/unlikely/libname.dylib',
                         '/usr/lib/libstdc++.6.dylib')
        lib_dict = tree_libs(subtree)
        copied = delocate_tree_libs(lib_dict, copy_dir, subtree)
        # Only the out-of-tree libraries get copied
        exp_dict = get_ext_dict(all_local_libs)
        assert_equal(copied, exp_dict)
        assert_equal(set(os.listdir(copy_dir)),
                     set([basename(realpath(lib)) for lib in EXT_LIBS]))
        # Libraries using the copied libraries now have an install name starting
        # with @loader_path, then pointing to the copied library directory
        for lib in all_local_libs:
            pathto_copies = relpath(realpath(copy_dir), dirname(realpath(lib)))
            lib_inames = get_install_names(lib)
            new_links = ['@loader_path/{0}/{1}'.format(pathto_copies,
                                                       basename(elib))
                         for elib in copied]
            assert_true(set(new_links) <= set(lib_inames))
        # Libraries now have a relative loader_path to their corresponding
        # in-tree libraries
        for requiring, using, rel_path in (
            (libb, 'liba.dylib', ''),
            (libc, 'liba.dylib', ''),
            (libc, 'libb.dylib', ''),
            (test_lib, 'libc.dylib', ''),
            (slibc, 'liba.dylib', '../'),
            (slibc, 'libb.dylib', '../'),
            (stest_lib, 'libc.dylib', '')):
            loader_path = '@loader_path/' + rel_path + using
            assert_true(loader_path in get_install_names(requiring))
        # Check test libs still work
        back_tick([test_lib])
        back_tick([stest_lib])
        # Check case where all local libraries are out of tree
        subtree2 = pjoin(tmpdir, 'subtree2')
        liba, libb, libc, test_lib, slibc, stest_lib = _make_libtree(subtree2)
        copy_dir2 = 'dynlibs2'
        os.makedirs(copy_dir2)
        # Trying to delocate where all local libraries appear to be
        # out-of-tree will raise an error because of duplicate library names
        # (libc and slibc both named <something>/libc.dylib)
        lib_dict2 = tree_libs(subtree2)
        assert_raises(DelocationError,
                      delocate_tree_libs, lib_dict2, copy_dir2, '/fictional')
        # Rename a library to make this work
        new_slibc = pjoin(dirname(slibc), 'libc2.dylib')
        os.rename(slibc, new_slibc)
        # Tell test-lib about this
        set_install_name(stest_lib, slibc, new_slibc)
        slibc = new_slibc
        # Confirm new test-lib still works
        back_tick([test_lib])
        back_tick([stest_lib])
        # Delocation now works
        lib_dict2 = tree_libs(subtree2)
        copied2 = delocate_tree_libs(lib_dict2, copy_dir2, '/fictional')
        local_libs = [liba, libb, libc, slibc, test_lib, stest_lib]
        rp_liba, rp_libb, rp_libc, rp_slibc, rp_test_lib, rp_stest_lib = \
                [realpath(L) for L in local_libs]
        exp_dict = get_ext_dict(local_libs)
        exp_dict.update({
            rp_libc: {rp_test_lib: libc},
            rp_slibc: {rp_stest_lib: slibc},
            rp_libb: {rp_slibc: libb,
                      rp_libc: libb},
            rp_liba: {rp_slibc: liba,
                      rp_libc: liba,
                      rp_libb: liba}})
        assert_equal(copied2, exp_dict)
        ext_local_libs = (set(realpath(L) for L in EXT_LIBS) |
                          set([liba, libb, libc, slibc]))
        assert_equal(set(os.listdir(copy_dir2)),
                     set([basename(lib) for lib in ext_local_libs]))
        # Libraries using the copied libraries now have an install name starting
        # with @loader_path, then pointing to the copied library directory
        all_local_libs = liba, libb, libc, test_lib, slibc, stest_lib
        for lib in all_local_libs:
            pathto_copies = relpath(realpath(copy_dir2),
                                    dirname(realpath(lib)))
            lib_inames = get_install_names(lib)
            new_links = ['@loader_path/{0}/{1}'.format(pathto_copies,
                                                       basename(elib))
                         for elib in copied]
            assert_true(set(new_links) <= set(lib_inames))


def _copy_fixpath(files, directory):
    new_fnames = []
    for fname in files:
        shutil.copy2(fname, directory)
        new_fname = pjoin(directory, basename(fname))
        for name in get_install_names(fname):
            if name.startswith('lib'):
                set_install_name(new_fname, name, pjoin(directory, name))
        new_fnames.append(new_fname)
    return new_fnames


def _copy_to(fname, directory, new_base):
    new_name = pjoin(directory, new_base)
    shutil.copy2(fname, new_name)
    return new_name


def test_copy_recurse():
    # Function to find / copy needed libraries recursively
    with InTemporaryDirectory():
        # Get some fixed up libraries to play with
        os.makedirs('libcopy')
        test_lib, liba, libb, libc = _copy_fixpath(
            [TEST_LIB, LIBA, LIBB, LIBC], 'libcopy')
        # Set execute permissions
        os.chmod(test_lib, 0o744)
        # Check system finds libraries
        back_tick(['./libcopy/test-lib'])
        # One library, depends only on system libs, system libs filtered
        def filt_func(libname):
            return not libname.startswith('/usr/lib')
        os.makedirs('subtree')
        _copy_fixpath([LIBA], 'subtree')
        # Nothing copied therefore
        assert_equal(copy_recurse('subtree', copy_filt_func=filt_func), {})
        assert_equal(set(os.listdir('subtree')), set(['liba.dylib']))
        # shortcut
        _rp = realpath
        # An object that depends on a library that depends on two libraries
        # test_lib depends on libc, libc depends on liba and libb. libc gets
        # copied first, then liba, libb
        def _st(fname):
            return _rp(pjoin('subtree2', basename(fname)))
        os.makedirs('subtree2')
        shutil.copy2(test_lib, 'subtree2')
        assert_equal(copy_recurse('subtree2', filt_func),
                     {_rp(libc): {_st(test_lib): libc},
                      _rp(libb): {_rp(libc): libb},
                      _rp(liba): {_rp(libb): liba,
                                  _rp(libc): liba}})
        assert_equal(set(os.listdir('subtree2')),
                     set(('liba.dylib',
                          'libb.dylib',
                          'libc.dylib',
                          'test-lib')))
        # A circular set of libraries
        os.makedirs('libcopy2')
        libw = _copy_to(LIBA, 'libcopy2', 'libw.dylib')
        libx = _copy_to(LIBA, 'libcopy2', 'libx.dylib')
        liby = _copy_to(LIBA, 'libcopy2', 'liby.dylib')
        libz = _copy_to(LIBA, 'libcopy2', 'libz.dylib')
        # targets and dependencies.  A copy of libw starts in the directory,
        # first pass should install libx and liby (dependencies of libw),
        # second pass should install libz, libw (dependencies of liby, libx
        # respectively)
        t_dep1_dep2 = (
            (libw, libx, liby), # libw depends on libx, liby
            (libx, libw, liby), # libx depends on libw, liby
            (liby, libw, libz), # liby depends on libw, libz
            (libz, libw, libx)) # libz depends on libw, libx
        for tlib, dep1, dep2 in t_dep1_dep2:
            set_install_name(tlib, EXT_LIBS[0], dep1)
            set_install_name(tlib, EXT_LIBS[1], dep2)
        os.makedirs('subtree3')
        seed_path = pjoin('subtree3', 'seed')
        shutil.copy2(libw, seed_path)
        assert_equal(copy_recurse('subtree3'), # not filtered
                     # First pass, libx, liby get copied
                     {_rp(libx): {_rp(seed_path): libx,
                                  _rp(libw): libx,
                                  _rp(libz): libx},
                      _rp(liby): {_rp(seed_path): liby,
                                  _rp(libw): liby,
                                  _rp(libx): liby},
                      _rp(libw): {_rp(libx): libw,
                                  _rp(liby): libw,
                                  _rp(libz): libw},
                      _rp(libz): {_rp(liby): libz}})
        assert_equal(set(os.listdir('subtree3')),
                     set(('seed',
                         'libw.dylib',
                          'libx.dylib',
                          'liby.dylib',
                          'libz.dylib')))
        for tlib, dep1, dep2 in t_dep1_dep2:
            out_lib = pjoin('subtree3', basename(tlib))
            assert_equal(set(get_install_names(out_lib)),
                         set(('@loader_path/' + basename(dep1),
                              '@loader_path/' + basename(dep2))))
        # Check case of not-empty copied_libs
        os.makedirs('subtree4')
        shutil.copy2(libw, 'subtree4')
        copied_libs = {_rp(libw): {_rp(libx): libw,
                                   _rp(liby): libw,
                                   _rp(libz): libw}}
        copied_copied = copied_libs.copy()
        assert_equal(copy_recurse('subtree4', None, copied_libs),
                     {_rp(libw): {_rp(libx): libw,
                                  _rp(liby): libw,
                                  _rp(libz): libw},
                      _rp(libx): {_rp(libw): libx,
                                  _rp(libz): libx},
                      _rp(liby): {_rp(libw): liby,
                                  _rp(libx): liby},
                      _rp(libz): {_rp(liby): libz}})
        # Not modified in-place
        assert_equal(copied_libs, copied_copied)


def test_copy_recurse_overwrite():
    # Check that copy_recurse won't overwrite pre-existing libs
    with InTemporaryDirectory():
        # Get some fixed up libraries to play with
        os.makedirs('libcopy')
        test_lib, liba, libb, libc = _copy_fixpath(
            [TEST_LIB, LIBA, LIBB, LIBC], 'libcopy')
        # Filter system libs
        def filt_func(libname):
            return not libname.startswith('/usr/lib')
        os.makedirs('subtree')
        # libb depends on liba
        shutil.copy2(libb, 'subtree')
        # If liba is already present, barf
        shutil.copy2(liba, 'subtree')
        assert_raises(DelocationError, copy_recurse, 'subtree', filt_func)
        # Works if liba not present
        os.unlink(pjoin('subtree', 'liba.dylib'))
        copy_recurse('subtree', filt_func)


def test_delocate_path():
    # Test high-level path delocator script
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree'))
        # Check it fixes up correctly
        assert_equal(delocate_path('subtree', 'deplibs'), {})
        assert_equal(len(os.listdir('deplibs')), 0)
        back_tick([test_lib])
        back_tick([stest_lib])
        # Make a fake external library to link to
        os.makedirs('fakelibs')
        fake_lib = realpath(_copy_to(LIBA, 'fakelibs', 'libfake.dylib'))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree2'))
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # shortcut
        _rp = realpath
        # Check fake libary gets copied and delocated
        slc_rel = pjoin('subtree2', 'subsub', 'libc.dylib')
        assert_equal(delocate_path('subtree2', 'deplibs2'),
                     {_rp(fake_lib): {_rp(slc_rel): fake_lib}})
        assert_equal(os.listdir('deplibs2'), ['libfake.dylib'])
        assert_true('@loader_path/../../deplibs2/libfake.dylib' in
                    get_install_names(slibc))
        # Unless we set the filter otherwise
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree3'))
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        def filt(libname):
            return not (libname.startswith('/usr') or
                        'libfake' in libname)
        assert_equal(delocate_path('subtree3', 'deplibs3', None, filt), {})
        assert_equal(len(os.listdir('deplibs3')), 0)
        # Test tree names filtering works
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree4'))
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        def lib_filt(filename):
            return not filename.endswith('subsub/libc.dylib')
        assert_equal(delocate_path('subtree4', 'deplibs4', lib_filt), {})
        assert_equal(len(os.listdir('deplibs4')), 0)
        # Check can use already existing directory
        os.makedirs('deplibs5')
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath('subtree5'))
        assert_equal(delocate_path('subtree5', 'deplibs5'), {})
        assert_equal(len(os.listdir('deplibs5')), 0)


def _make_bare_depends():
    # Copy:
    # * liba.dylib to 'libs' dir, which is a dependency of libb.dylib
    # * libb.dylib to 'subtree' dir, as 'libb' (no extension).
    #
    # This is for testing delocation when the depending file does not have a
    # dynamic library file extension.
    libb, = _copy_libs([LIBB], 'subtree')
    liba, = _copy_libs([LIBA], 'libs')
    bare_b, _ = splitext(libb)
    os.rename(libb, bare_b)
    # use realpath for OSX /private/var - /var
    set_install_name(bare_b, 'liba.dylib', realpath(liba))
    return liba, bare_b


def test_delocate_path_dylibs():
    # Test options for delocating everything, or just dynamic libraries
    _rp = realpath  # shortcut
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        assert_equal(delocate_path('subtree', 'deplibs',
                                   lib_filt_func='dylibs-only'), {})
        assert_equal(len(os.listdir('deplibs')), 0)
        # None - does inspect non-dylib files
        assert_equal(delocate_path('subtree', 'deplibs', None),
                     {_rp(pjoin('libs', 'liba.dylib')):
                      {_rp(bare_b): _rp(liba)}})
        assert_equal(os.listdir('deplibs'), ['liba.dylib'])
    with InTemporaryDirectory():
        # Callable, dylibs only, does not inspect
        liba, bare_b = _make_bare_depends()
        func = lambda fn : fn.endswith('.dylib')
        assert_equal(delocate_path('subtree', 'deplibs', func), {})
        func = lambda fn : fn.endswith('libb')
        assert_equal(delocate_path('subtree', 'deplibs', None),
                     {_rp(pjoin('libs', 'liba.dylib')):
                      {_rp(bare_b): _rp(liba)}})


def test_check_archs():
    # Test utility to check architectures in copied_libs dict
    # No libs always OK
    s0 = set()
    assert_equal(check_archs({}), s0)
    # One lib to itself OK
    lib_32_32 = {LIB32: {LIB32: 'install_name'}}
    lib_64_64 = {LIB64: {LIB64: 'install_name'}}
    assert_equal(check_archs(lib_32_32), s0)
    assert_equal(check_archs(lib_64_64), s0)
    # OK matching to another static lib of same arch
    assert_equal(check_archs({LIB64A: {LIB64: 'install_name'}}), s0)
    # Or two libs
    two_libs = {LIB64A: {LIB64: 'install_name'},
                LIB32: {LIB32: 'install_name'}}
    assert_equal(check_archs(two_libs), s0)
    # Same as empty sequence required_args argument
    assert_equal(check_archs(lib_32_32, ()), s0)
    assert_equal(check_archs(lib_64_64, ()), s0)
    assert_equal(check_archs(two_libs, ()), s0)
    assert_equal(check_archs(two_libs, []), s0)
    assert_equal(check_archs(two_libs, set()), s0)
    # bads if we require more archs than present
    for in_libs, exp_arch, missing in ((lib_32_32, ARCH_64, ARCH_64),
                                       (lib_32_32, ARCH_BOTH, ARCH_64),
                                       (lib_32_32, 'x86_64', ARCH_64),
                                       (lib_32_32, 'intel', ARCH_64),
                                       (lib_64_64, ARCH_32, ARCH_32),
                                       (lib_64_64, ARCH_BOTH, ARCH_32),
                                       (lib_64_64, 'i386', ARCH_32),
                                       (lib_64_64, 'intel', ARCH_32)):
        ded, value = list(in_libs.items())[0]
        ding, _ = list(value.items())[0]
        assert_equal(check_archs(in_libs, exp_arch),
                     set([(ding, missing)]))
    # Two libs
    assert_equal(check_archs(two_libs, ARCH_32),
                 set([(LIB64, ARCH_32)]))
    assert_equal(check_archs(two_libs, ARCH_64),
                 set([(LIB32, ARCH_64)]))
    assert_equal(check_archs(two_libs, ARCH_BOTH),
                 set([(LIB64, ARCH_32), (LIB32, ARCH_64)]))
    # Libs must match architecture with second arg of None
    assert_equal(check_archs(
        {LIB64: {LIB32: 'install_name'}}),
        set([(LIB64, LIB32, ARCH_32)]))
    assert_equal(check_archs(
        {LIB64A: {LIB64: 'install_name'},
         LIB32: {LIB32: 'install_name'},
         LIB64: {LIB32: 'install_name'}}),
        set([(LIB64, LIB32, ARCH_32)]))
    # For single archs depending, dual archs in depended is OK
    assert_equal(check_archs(
        {LIBBOTH: {LIB64A: 'install_name'}}),
         s0)
    # For dual archs in depending, both must be present
    assert_equal(check_archs(
        {LIBBOTH: {LIBBOTH: 'install_name'}}),
        s0)
    assert_equal(check_archs(
        {LIB64A: {LIBBOTH: 'install_name'}}),
        set([(LIB64A, LIBBOTH, ARCH_32)]))
    # More than one bad
    in_dict = {LIB64A: {LIBBOTH: 'install_name'},
               LIB64: {LIB32: 'install_name'}}
    exp_res = set([(LIB64A, LIBBOTH, ARCH_32),
                   (LIB64, LIB32, ARCH_32)])
    assert_equal(check_archs(in_dict), exp_res)
    # Check stop_fast flag; can't predict return, but there should only be one
    stopped = check_archs(in_dict, (), True)
    assert_equal(len(stopped), 1)
    # More than one bad in dependings
    assert_equal(check_archs(
        {LIB64A: {LIBBOTH: 'install_name',
                  LIB32: 'install_name'},
         LIB64: {LIB32: 'install_name'}}),
        set([(LIB64A, LIBBOTH, ARCH_32),
             (LIB64A, LIB32, ARCH_32),
             (LIB64, LIB32, ARCH_32)]))


def test_bads_report():
    # Test bads_report of architecture errors
    # No bads, no report
    assert_equal(bads_report([]), '')
    fmt_str_2 = 'Required arch i386 missing from {0}'
    fmt_str_3 = '{0} needs arch i386 missing from {1}'
    # One line report
    assert_equal(bads_report(set([(LIB64, LIB32, ARCH_32)])),
                 fmt_str_3.format(LIB32, LIB64))
    # One line report applying path stripper
    assert_equal(bads_report(set([(LIB64, LIB32, ARCH_32)]), dirname(LIB64)),
                 fmt_str_3.format(basename(LIB32), basename(LIB64)))
    # Multi-line report
    assert_equal(bads_report(set([(LIB64A, LIBBOTH, ARCH_32),
                                  (LIB64A, LIB32, ARCH_32),
                                  (LIB64, LIB32, ARCH_32)])),
                 '\n'.join([fmt_str_3.format(LIB32, LIB64A),
                            fmt_str_3.format(LIB32, LIB64),
                            fmt_str_3.format(LIBBOTH, LIB64A)]))
    # Two tuples and three tuples
    assert_equal(bads_report(set([(LIB64A, LIBBOTH, ARCH_32),
                                  (LIB64, ARCH_32),
                                  (LIB32, ARCH_32)])),
                 '\n'.join([fmt_str_3.format(LIBBOTH, LIB64A),
                            fmt_str_2.format(LIB64),
                            fmt_str_2.format(LIB32)]))
    # Tuples must be length 2 or 3
    assert_raises(ValueError,
                  bads_report,
                  set([(LIB64A, LIBBOTH, ARCH_32),
                       (LIB64,),
                       (LIB32, ARCH_32)]))
    # Tuples must be length 2 or 3
    assert_raises(ValueError,
                  bads_report,
                  set([(LIB64A, LIBBOTH, ARCH_32),
                       (LIB64, LIB64, ARCH_32, ARCH_64),
                       (LIB32, ARCH_32)]))

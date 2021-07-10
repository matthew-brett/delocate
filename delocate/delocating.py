""" Routines to copy / relink library dependencies in trees and wheels
"""

from __future__ import division, print_function

import os
from os.path import (join as pjoin, dirname, basename, exists, abspath,
                     relpath, realpath)
import logging
import shutil
import warnings
from subprocess import Popen, PIPE
from typing import (Callable, Dict, FrozenSet, Iterable, List, Mapping,
                    Optional, Set, Text, Tuple, Union)

from .pycompat import string_types
from .libsana import (tree_libs, stripped_lib_dict, get_rp_stripper,
                      walk_directory, get_dependencies)
from .tools import (set_install_name, zip2dir, dir2zip, validate_signature,
                    find_package_dirs, set_install_id, get_archs)
from .tmpdirs import TemporaryDirectory
from .wheeltools import rewrite_record, InWheel


logger = logging.getLogger(__name__)

# Prefix for install_name_id of copied libraries
DLC_PREFIX = '/DLC/'


class DelocationError(Exception):
    pass


def delocate_tree_libs(
    lib_dict,  # type: Mapping[Text, Mapping[Text, Text]]
    lib_path,  # type: Text
    root_path  # type: Text
):
    # type: (...) -> Dict[Text, Dict[Text, Text]]
    """ Move needed libraries in `lib_dict` into `lib_path`

    `lib_dict` has keys naming libraries required by the files in the
    corresponding value.  Call the keys, "required libs".  Call the values
    "requiring objects".

    Copy all the required libs to `lib_path`.  Fix up the rpaths and install
    names in the requiring objects to point to these new copies.

    Exception: required libs within the directory tree pointed to by
    `root_path` stay where they are, but we modify requiring objects to use
    relative paths to these libraries.

    Parameters
    ----------
    lib_dict : dict
        Dictionary with (key, value) pairs of (``depended_lib_path``,
        ``dependings_dict``) (see :func:`libsana.tree_libs`)
    lib_path : str
        Path in which to store copies of libs referred to in keys of
        `lib_dict`.  Assumed to exist
    root_path : str
        Root directory of tree analyzed in `lib_dict`.  Any required
        library within the subtrees of `root_path` does not get copied, but
        libraries linking to it have links adjusted to use relative path to
        this library.

    Returns
    -------
    copied_libs : dict
        Filtered `lib_dict` dict containing only the (key, value) pairs from
        `lib_dict` where the keys are the libraries copied to `lib_path``.

    Raises
    ------
    DelocationError
        When a malformed `lib_dict` has unresolved paths, missing files, etc.
        When two dependencies would've been be copied to the same destination.
    """
    # Test for errors first to avoid getting half-way through changing the tree
    libraries_to_copy, libraries_to_delocate = _analyze_tree_libs(
        lib_dict, root_path
    )
    # Copy libraries and update lib_dict.
    lib_dict, copied_libraries = _copy_required_libs(
        lib_dict, lib_path, root_path, libraries_to_copy
    )
    # Update the install names of local and copied libaries.
    _update_install_names(
        lib_dict, root_path, libraries_to_delocate | copied_libraries
    )
    return libraries_to_copy


def _analyze_tree_libs(
    lib_dict,  # type: Mapping[Text, Mapping[Text, Text]]
    root_path  # type: Text
):
    # type: (...) -> Tuple[Dict[Text, Dict[Text, Text]], Set[Text]]
    """ Verify then return which library files to copy and delocate.

    Returns
    -------
    needs_copying : dict
        The libraries outside of `root_path`.
        This is in the `lib_dict` format for use by `delocate_tree_libs`.
    needs_delocating : set of str
        The libraries inside of `root_path` which need to be delocated.
    """
    needs_delocating = set()  # Libraries which need install names updated.
    needs_copying = {}  # A report of which libraries were copied.
    copied_basenames = set()
    rp_root_path = realpath(root_path)
    for required, requirings in lib_dict.items():
        if required.startswith('@'):
            # @rpath, etc, at this point should never happen.
            raise DelocationError("%s was expected to be resolved." % required)
        r_ed_base = basename(required)
        if relpath(required, rp_root_path).startswith('..'):
            # Not local, plan to copy
            if r_ed_base in copied_basenames:
                raise DelocationError('Already planning to copy library with '
                                      'same basename as: ' + r_ed_base)
            if not exists(required):
                raise DelocationError('library "{0}" does not exist'.format(
                    required))
            # Copy requirings to preserve it since it will be modified later.
            needs_copying[required] = dict(requirings)
            copied_basenames.add(r_ed_base)
        else:  # Is local, plan to set relative loader_path
            needs_delocating.add(required)
    return needs_copying, needs_delocating


def _copy_required_libs(
    lib_dict,  # type: Mapping[Text, Mapping[Text, Text]]
    lib_path,  # type: Text
    root_path,  # type: Text
    libraries_to_copy  # type: Iterable[Text]
):
    # type (...) -> Tuple[Dict[Text, Dict[Text, Text]], Set[Text]]
    """ Copy libraries outside of root_path to lib_path.

    Returns
    -------
    updated_lib_dict : dict
        A copy of `lib_dict` modified so that dependencies now point to
        the copied library destinations.
    needs_delocating : set of str
        A set of the destination files, these need to be delocated.
    """
    # Create a copy of lib_dict for this script to modify and return.
    out_lib_dict = _copy_lib_dict(lib_dict)
    del lib_dict
    needs_delocating = set()  # Set[Text]
    for old_path in libraries_to_copy:
        new_path = realpath(pjoin(lib_path, basename(old_path)))
        logger.info(
            "Copying library %s to %s", old_path, relpath(new_path, root_path)
        )
        shutil.copy(old_path, new_path)
        # Delocate this file now that it is stored locally.
        needs_delocating.add(new_path)
        # Update out_lib_dict with the new file paths.
        out_lib_dict[new_path] = out_lib_dict[old_path]
        del out_lib_dict[old_path]
        for required in out_lib_dict:
            if old_path not in out_lib_dict[required]:
                continue
            out_lib_dict[required][new_path] = out_lib_dict[required][old_path]
            del out_lib_dict[required][old_path]
    return out_lib_dict, needs_delocating


def _update_install_names(
    lib_dict,  # type: Mapping[Text, Mapping[Text, Text]]
    root_path,  # type: Text
    files_to_delocate  # type: Iterable[Text]
):
    # type: (...) -> None
    """ Update the install names of libraries. """
    for required in files_to_delocate:
        # Set relative path for local library
        for requiring, orig_install_name in lib_dict[required].items():
            req_rel = relpath(required, dirname(requiring))
            new_install_name = '@loader_path/' + req_rel
            logger.info(
                "Modifying install name in %s from %s to %s",
                relpath(requiring, root_path),
                orig_install_name,
                new_install_name,
            )
            set_install_name(requiring, orig_install_name, new_install_name)


def copy_recurse(
    lib_path,  # type: Text
    copy_filt_func=None,  # type: Optional[Callable[[Text], bool]]
    copied_libs=None  # type: Optional[Dict[Text, Dict[Text, Text]]]
):
    # type: (...) -> Dict[Text, Dict[Text, Text]]
    """ Analyze `lib_path` for library dependencies and copy libraries

    `lib_path` is a directory containing libraries.  The libraries might
    themselves have dependencies.  This function analyzes the dependencies and
    copies library dependencies that match the filter `copy_filt_func`. It also
    adjusts the depending libraries to use the copy. It keeps iterating over
    `lib_path` until all matching dependencies (of dependencies of dependencies
    ...) have been copied.

    Parameters
    ----------
    lib_path : str
        Directory containing libraries
    copy_filt_func : None or callable, optional
        If None, copy any library that found libraries depend on.  If callable,
        called on each depended library name; copy where
        ``copy_filt_func(libname)`` is True, don't copy otherwise
    copied_libs : dict
        Dict with (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``) where ``copied_lib_path`` is the canonical path of
        a library that has been copied to `lib_path`, and ``dependings_dict``
        is a dictionary with (key, value) pairs of (``depending_lib_path``,
        ``install_name``).  ``depending_lib_path`` is the canonical path of the
        library depending on ``copied_lib_path``, ``install_name`` is the name
        that ``depending_lib_path`` uses to refer to ``copied_lib_path`` (in
        its install names).

    Returns
    -------
    copied_libs : dict
        Input `copied_libs` dict with any extra libraries and / or dependencies
        added.

    .. deprecated:: 0.9
        This function is obsolete.  :func:`delocate_path` handles recursive
        dependencies while also supporting `@loader_path`.
    """
    warnings.warn(
        "copy_recurse is obsolete and should no longer be called.",
        DeprecationWarning,
        stacklevel=2,
    )
    if copied_libs is None:
        copied_libs = {}
    else:
        copied_libs = dict(copied_libs)
    done = False
    while not done:
        in_len = len(copied_libs)
        _copy_required(lib_path, copy_filt_func, copied_libs)
        done = len(copied_libs) == in_len
    return copied_libs


def _copy_required(
    lib_path,  # type: Text
    copy_filt_func,  # type: Optional[Callable[[Text], bool]]
    copied_libs  # type: Dict[Text, Dict[Text, Text]]
):
    # type: (...) -> None
    """ Copy libraries required for files in `lib_path` to `copied_libs`

    Augment `copied_libs` dictionary with any newly copied libraries, modifying
    `copied_libs` in-place - see Notes.

    This is one pass of ``copy_recurse``

    Parameters
    ----------
    lib_path : str
        Directory containing libraries
    copy_filt_func : None or callable, optional
        If None, copy any library that found libraries depend on.  If callable,
        called on each library name; copy where ``copy_filt_func(libname)`` is
        True, don't copy otherwise
    copied_libs : dict
        See :func:`copy_recurse` for definition.

    Notes
    -----
    If we need to copy another library, add that (``depended_lib_path``,
    ``dependings_dict``) to `copied_libs`.  ``dependings_dict`` has (key,
    value) pairs of (``depending_lib_path``, ``install_name``).
    ``depending_lib_path`` will be the original (canonical) library name, not
    the copy in ``lib_path``.

    Sometimes we copy a library, that further depends on a library we have
    already copied. In this case update ``copied_libs[depended_lib]`` with the
    extra dependency (as well as fixing up the install names for the depending
    library).

    For example, imagine we've start with a lib path like this::

        my_lib_path/
            libA.dylib
            libB.dylib

    Our input `copied_libs` has keys ``/sys/libA.dylib``, ``/sys/libB.lib``
    telling us we previously copied those guys from the ``/sys`` folder.

    On a first pass, we discover that ``libA.dylib`` depends on
    ``/sys/libC.dylib``, so we copy that.

    On a second pass, we discover now that ``libC.dylib`` also depends on
    ``/sys/libB.dylib``.  `copied_libs` tells us that we already have a copy of
    ``/sys/libB.dylib``, so we fix our copy of `libC.dylib`` to point to
    ``my_lib_path/libB.dylib`` and add ``/sys/libC.dylib`` as a
    ``dependings_dict`` entry for ``copied_libs['/sys/libB.dylib']``

    .. deprecated:: 0.9
        This function is obsolete, and is only used by :func:`copy_recurse`.
    """
    # Paths will be prepended with `lib_path`
    lib_dict = tree_libs(lib_path)
    # Map library paths after copy ('copied') to path before copy ('orig')
    rp_lp = realpath(lib_path)
    copied2orig = dict((pjoin(rp_lp, basename(c)), c) for c in copied_libs)
    for required, requirings in lib_dict.items():
        if copy_filt_func is not None and not copy_filt_func(required):
            continue
        if required.startswith('@'):
            # May have been processed by us, or have some rpath, loader_path of
            # its own. Either way, leave alone
            continue
        # Requiring names may well be the copies in lib_path.  Replace the copy
        # names with the original names for entry into `copied_libs`
        procd_requirings = {}
        # Set requiring lib install names to point to local copy
        for requiring, orig_install_name in requirings.items():
            set_install_name(requiring,
                             orig_install_name,
                             '@loader_path/' + basename(required))
            # Make processed version of ``dependings_dict``
            mapped_requiring = copied2orig.get(requiring, requiring)
            procd_requirings[mapped_requiring] = orig_install_name
        if required in copied_libs:
            # Have copied this already, add any new requirings
            copied_libs[required].update(procd_requirings)
            continue
        # Haven't see this one before, add entry to copied_libs
        out_path = pjoin(lib_path, basename(required))
        if exists(out_path):
            raise DelocationError(out_path + ' already exists')
        shutil.copy(required, lib_path)
        copied2orig[out_path] = required
        copied_libs[required] = procd_requirings


def _dylibs_only(filename):
    # type: (Text) -> bool
    return (filename.endswith('.so') or
            filename.endswith('.dylib'))


def filter_system_libs(libname):
    # type: (Text) -> bool
    return not (libname.startswith('/usr/lib') or
                libname.startswith('/System'))


def delocate_path(
    tree_path,  # type: Text
    lib_path,  # type: Text
    lib_filt_func=None,  # type: Optional[Union[str, Callable[[Text], bool]]]
    copy_filt_func=filter_system_libs,  # type: Optional[Callable[[Text], bool]]
    executable_path=None,  # type: Optional[Text]
    ignore_missing=False,  # type: bool
):
    # type: (...) -> Dict[Text, Dict[Text, Text]]
    """ Copy required libraries for files in `tree_path` into `lib_path`

    Parameters
    ----------
    tree_path : str
        Root path of tree to search for required libraries
    lib_path : str
        Directory into which we copy required libraries
    lib_filt_func : None or str or callable, optional
        If None, inspect all files for dependencies on dynamic libraries. If
        callable, accepts filename as argument, returns True if we should
        inspect the file, False otherwise. If str == "dylibs-only" then inspect
        only files with known dynamic library extensions (``.dylib``, ``.so``).
    copy_filt_func : None or callable, optional
        If callable, called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
        Default is callable rejecting only libraries beginning with
        ``/usr/lib`` or ``/System``.  None means copy all libraries. This will
        usually end up copying large parts of the system run-time.
    executable_path : None or str, optional
        If not None, an alternative path to use for resolving
        `@executable_path`.
    ignore_missing : bool, default=False
        Continue even if missing dependencies are detected.

    Returns
    -------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that was copied into `lib_sdir` of the wheel packages, and
        ``dependings_dict`` is a dictionary with key, value pairs where the key
        is a file in the path depending on ``copied_lib_path``, and the value
        is the ``install_name`` of ``copied_lib_path`` in the depending
        library.

    Raises
    ------
    DelocationError
        When any dependencies can not be located.
    """
    if lib_filt_func == "dylibs-only":
        lib_filt_func = _dylibs_only
    elif isinstance(lib_filt_func, str):
        raise TypeError('lib_filt_func string can only be "dylibs-only"')
    if lib_filt_func is None:
        lib_filt_func = (lambda _: True)
    if not exists(lib_path):
        os.makedirs(lib_path)

    lib_dict = {}  # type: Dict[Text, Dict[Text, Text]]
    missing_libs = False
    for library_path in walk_directory(
        tree_path, lib_filt_func, executable_path=executable_path
    ):
        for depending_path, install_name in get_dependencies(
            library_path, executable_path=executable_path
        ):
            if depending_path is None:
                missing_libs = True
                continue
            if copy_filt_func and not copy_filt_func(depending_path):
                continue
            lib_dict.setdefault(depending_path, {})
            lib_dict[depending_path][library_path] = install_name

    if missing_libs and not ignore_missing:
        # Details of missing libraries would have already reported by
        # get_dependencies.
        raise DelocationError("Could not find all dependencies.")

    return delocate_tree_libs(lib_dict, lib_path, tree_path)


def _copy_lib_dict(lib_dict):
    # type: (Mapping[Text, Mapping[Text, Text]]) -> Dict[Text, Dict[Text, Text]]  # noqa: E501
    """ Returns a copy of lib_dict. """
    return {  # Convert nested Mapping types into nested Dict types.
        required: dict(requiring) for required, requiring in lib_dict.items()
    }


def _merge_lib_dict(d1, d2):
    # type: (Dict[Text, Dict[Text, Text]], Mapping[Text, Mapping[Text, Text]]) -> None  # noqa: E501
    """ Merges lib_dict `d2` into lib_dict `d1`
    """
    for required, requirings in d2.items():
        if required in d1:
            d1[required].update(requirings)
        else:
            # Convert to dict to satisfy type checking.
            d1[required] = dict(requirings)
    return None


def delocate_wheel(
    in_wheel,  # type: Text
    out_wheel=None,  # type: Optional[Text]
    lib_sdir='.dylibs',  # type: Text
    lib_filt_func=None,  # type: Union[None, str, Callable[[Text], bool]]
    copy_filt_func=filter_system_libs,  # type: Optional[Callable[[Text], bool]]
    require_archs=None,  # type: Union[None, Text, Iterable[Text]]
    check_verbose=False,  # type: bool
    executable_path=None,  # type: Optional[Text]
    ignore_missing=False,  # type: bool
):
    # type: (...) -> Dict[Text, Dict[Text, Text]]
    """ Update wheel by copying required libraries to `lib_sdir` in wheel

    Create `lib_sdir` in wheel tree only if we are copying one or more
    libraries.

    If `out_wheel` is None (the default), overwrite the wheel `in_wheel`
    in-place.

    Parameters
    ----------
    in_wheel : str
        Filename of wheel to process
    out_wheel : None or str
        Filename of processed wheel to write.  If None, overwrite `in_wheel`
    lib_sdir : str, optional
        Subdirectory name in wheel package directory (or directories) to store
        needed libraries.
    lib_filt_func : None or str or callable, optional
        If None, inspect all files for dependencies on dynamic libraries. If
        callable, accepts filename as argument, returns True if we should
        inspect the file, False otherwise. If str == "dylibs-only" then inspect
        only files with known dynamic library extensions (``.dylib``, ``.so``).
    copy_filt_func : None or callable, optional
        If callable, called on each library name detected as a dependency; copy
        where ``copy_filt_func(libname)`` is True, don't copy otherwise.
        Default is callable rejecting only libraries beginning with
        ``/usr/lib`` or ``/System``.  None means copy all libraries. This will
        usually end up copying large parts of the system run-time.
    require_archs : None or str or sequence, optional
        If None, do no checks of architectures in libraries.  If sequence,
        sequence of architectures (output from ``lipo -info``) that every
        library in the wheels should have (e.g. ``['x86_64, 'i386']``). An
        empty sequence results in checks that depended libraries have the same
        archs as depending libraries.  If string, either "intel" (corresponds
        to sequence ``['x86_64, 'i386']``) or name of required architecture
        (e.g "i386" or "x86_64").
    check_verbose : bool, optional
        If True, print warning messages about missing required architectures
    executable_path : str, optional
        An alternative path to use for resolving `@executable_path`.
    ignore_missing : bool, default=False
        Continue even if missing dependencies are detected.

    Returns
    -------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that was copied into `lib_sdir` of the wheel packages, and
        ``dependings_dict`` is a dictionary with key, value pairs where the key
        is a path in the wheel depending on ``copied_lib_path``, and the value
        is the ``install_name`` of ``copied_lib_path`` in the depending
        library. The filenames in the keys are relative to the wheel root path.
    """
    in_wheel = abspath(in_wheel)
    if out_wheel is None:
        out_wheel = in_wheel
    else:
        out_wheel = abspath(out_wheel)
    in_place = in_wheel == out_wheel
    with TemporaryDirectory() as tmpdir:
        all_copied = {}  # type: Dict[Text, Dict[Text, Text]]
        wheel_dir = realpath(pjoin(tmpdir, 'wheel'))
        zip2dir(in_wheel, wheel_dir)
        for package_path in find_package_dirs(wheel_dir):
            lib_path = pjoin(package_path, lib_sdir)
            lib_path_exists = exists(lib_path)
            copied_libs = delocate_path(
                package_path,
                lib_path,
                lib_filt_func,
                copy_filt_func,
                executable_path=executable_path,
                ignore_missing=ignore_missing,
            )
            if copied_libs and lib_path_exists:
                raise DelocationError(
                    '{0} already exists in wheel but need to copy '
                    '{1}'.format(lib_path, '; '.join(copied_libs)))
            if len(os.listdir(lib_path)) == 0:
                shutil.rmtree(lib_path)
            # Check architectures
            if require_archs is not None:
                stop_fast = not check_verbose
                bads = check_archs(copied_libs, require_archs, stop_fast)
                if len(bads) != 0:
                    if check_verbose:
                        print(bads_report(bads, pjoin(tmpdir, 'wheel')))
                    raise DelocationError(
                        "Some missing architectures in wheel")
            # Change install ids to be unique within Python space
            install_id_root = (DLC_PREFIX +
                               relpath(package_path, wheel_dir) +
                               '/')
            for lib in copied_libs:
                lib_base = basename(lib)
                copied_path = pjoin(lib_path, lib_base)
                set_install_id(copied_path, install_id_root + lib_base)
                validate_signature(copied_path)
            _merge_lib_dict(all_copied, copied_libs)
        if len(all_copied):
            rewrite_record(wheel_dir)
        if len(all_copied) or not in_place:
            dir2zip(wheel_dir, out_wheel)
    return stripped_lib_dict(all_copied, wheel_dir + os.path.sep)


def patch_wheel(in_wheel, patch_fname, out_wheel=None):
    # type: (Text, Text, Optional[Text]) -> None
    """ Apply ``-p1`` style patch in `patch_fname` to contents of `in_wheel`

    If `out_wheel` is None (the default), overwrite the wheel `in_wheel`
    in-place.

    Parameters
    ----------
    in_wheel : str
        Filename of wheel to process
    patch_fname : str
        Filename of patch file.  Will be applied with ``patch -p1 <
        patch_fname``
    out_wheel : None or str
        Filename of patched wheel to write.  If None, overwrite `in_wheel`
    """
    in_wheel = abspath(in_wheel)
    patch_fname = abspath(patch_fname)
    if out_wheel is None:
        out_wheel = in_wheel
    else:
        out_wheel = abspath(out_wheel)
    if not exists(patch_fname):
        raise ValueError("patch file {0} does not exist".format(patch_fname))
    with InWheel(in_wheel, out_wheel):
        with open(patch_fname, 'rb') as fobj:
            patch_proc = Popen(['patch', '-p1'],
                               stdin=fobj,
                               stdout=PIPE,
                               stderr=PIPE)
            stdout, stderr = patch_proc.communicate()
            if patch_proc.returncode != 0:
                raise RuntimeError("Patch failed with stdout:\n" +
                                   stdout.decode('latin1'))


_ARCH_LOOKUP = {
    'intel': ['i386', 'x86_64'],
    'universal2': ['x86_64', 'arm64']
}


def check_archs(
    copied_libs,  # type: Mapping[Text, Mapping[Text, Text]]
    require_archs=(),  # type:  Union[Text, Iterable[Text]]
    stop_fast=False  # type: bool
):
    # type: (...) -> Set[Union[Tuple[Text, FrozenSet[Text]], Tuple[Text, Text, FrozenSet[Text]]]]  # noqa: E501
    """ Check compatibility of archs in `copied_libs` dict

    Parameters
    ----------
    copied_libs : dict
        dict containing the (key, value) pairs of (``copied_lib_path``,
        ``dependings_dict``), where ``copied_lib_path`` is a library real path
        that has been copied during delocation, and ``dependings_dict`` is a
        dictionary with key, value pairs where the key is a path in the target
        being delocated (a wheel or path) depending on ``copied_lib_path``, and
        the value is the ``install_name`` of ``copied_lib_path`` in the
        depending library.
    require_archs : str or sequence, optional
        Architectures we require to be present in all library files in wheel.
        If an empty sequence, just check that depended libraries do have the
        architectures of the depending libraries, with no constraints on what
        these architectures are. If a sequence, then a set of required
        architectures e.g. ``['i386', 'x86_64']`` to specify dual Intel
        architectures.  If a string, then a standard architecture name as
        returned by ``lipo -info``, or the string "intel", corresponding to the
        sequence ``['i386', 'x86_64']``, or the string "universal2",
        corresponding to ``['x86_64', 'arm64']``.
    stop_fast : bool, optional
        Whether to give up collecting errors after the first

    Returns
    -------
    bads : set
        set of length 2 or 3 tuples. A length 2 tuple is of form
        ``(depending_lib, missing_archs)`` meaning that an arch in
        `require_archs` was missing from ``depending_lib``.  A length 3 tuple
        is of form ``(depended_lib, depending_lib, missing_archs)`` where
        ``depended_lib`` is the filename of the library depended on,
        ``depending_lib`` is the library depending on ``depending_lib`` and
        ``missing_archs`` is a set of missing architecture strings giving
        architectures present in ``depending_lib`` and missing in
        ``depended_lib``.  An empty set means all architectures were present as
        required.
    """
    if isinstance(require_archs, string_types):
        require_archs = _ARCH_LOOKUP.get(require_archs, [require_archs])
    require_archs_set = frozenset(require_archs)
    bads = []  # type: List[Union[Tuple[Text, FrozenSet[Text]], Tuple[Text, Text, FrozenSet[Text]]]]  # noqa: E501
    for depended_lib, dep_dict in copied_libs.items():
        depended_archs = get_archs(depended_lib)
        for depending_lib, install_name in dep_dict.items():
            depending_archs = get_archs(depending_lib)
            all_required = depending_archs | require_archs_set
            all_missing = all_required.difference(depended_archs)
            if len(all_missing) == 0:
                continue
            required_missing = require_archs_set.difference(depended_archs)
            if len(required_missing):
                bads.append((depending_lib, required_missing))
            else:
                bads.append((depended_lib, depending_lib, all_missing))
            if stop_fast:
                return set(bads)
    return set(bads)


def bads_report(bads, path_prefix=None):
    """ Return a nice report of bad architectures in `bads`

    Parameters
    ----------
    bads : set
        set of length 2 or 3 tuples. A length 2 tuple is of form
        ``(depending_lib, missing_archs)`` meaning that an arch in
        `require_archs` was missing from ``depending_lib``.  A length 3 tuple
        is of form ``(depended_lib, depending_lib, missing_archs)`` where
        ``depended_lib`` is the filename of the library depended on,
        ``depending_lib`` is the library depending on ``depending_lib`` and
        ``missing_archs`` is a set of missing architecture strings giving
        architectures present in ``depending_lib`` and missing in
        ``depended_lib``.  An empty set means all architectures were present as
        required.
    path_prefix : None or str, optional
        Path prefix to strip from ``depended_lib`` and ``depending_lib``. None
        means do not strip anything.

    Returns
    -------
    report : str
        A nice report for printing
    """
    path_processor = ((lambda x: x) if path_prefix is None
                      else get_rp_stripper(path_prefix))
    reports = []
    for result in bads:
        if len(result) == 3:
            depended_lib, depending_lib, missing_archs = result
            reports.append("{0} needs {1} {2} missing from {3}".format(
                path_processor(depending_lib),
                'archs' if len(missing_archs) > 1 else 'arch',
                ', '.join(sorted(missing_archs)),
                path_processor(depended_lib)))
        elif len(result) == 2:
            depending_lib, missing_archs = result
            reports.append("Required {0} {1} missing from {2}".format(
                'archs' if len(missing_archs) > 1 else 'arch',
                ', '.join(sorted(missing_archs)),
                path_processor(depending_lib)))
        else:
            raise ValueError('Report tuple should be length 2 or 3')
    return '\n'.join(sorted(reports))

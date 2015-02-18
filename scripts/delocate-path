#!python
""" Copy, relink library dependencies for libraries in path
"""
# vim: ft=python
from __future__ import division, print_function, absolute_import

import sys
import os
from optparse import OptionParser, Option

from delocate import delocate_path, __version__

def main():
    parser = OptionParser(
        usage="%s PATH_TO_ANALYZE\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__)
    parser.add_options([
        Option("-L", "--lib-path",
               action="store", type='string',
               help="Output subdirectory path to copy library dependencies"),
        Option("-d", "--dylibs-only",
               action="store_true",
               help="Only analyze files with known dynamic library "
               "extensions")])
    (opts, paths) = parser.parse_args()
    if len(paths) < 1:
        parser.print_help()
        sys.exit(1)

    if opts.lib_path is None:
        opts.lib_path = '.dylibs'
    lib_filt_func = 'dylibs-only' if opts.dylibs_only else None
    multi = len(paths) > 1
    for path in paths:
        if multi:
            print(path)
        # evaluate paths relative to the path we are working on
        lib_path = os.path.join(path, opts.lib_path)
        delocate_path(path, lib_path, lib_filt_func)


if __name__ == '__main__':
    main()

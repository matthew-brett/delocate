#!python
""" List library dependencies for libraries in path or wheel
"""
# vim: ft=python
from __future__ import division, print_function, absolute_import

import sys
from os import getcwd
from os.path import isdir, realpath, sep as psep
from optparse import OptionParser, Option

from delocate import tree_libs, wheel_libs, __version__
from delocate.delocating import filter_system_libs
from delocate.libsana import stripped_lib_dict


def main():
    parser = OptionParser(
        usage="%s WHEEL_OR_PATH_TO_ANALYZE\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__)
    parser.add_options([
        Option("-a", "--all",
               action="store_true",
               help="Show all dependencies, including system libs"),
        Option("-d", "--depending",
               action="store_true",
               help="Show libraries depending on dependencies")])
    (opts, paths) = parser.parse_args()
    if len(paths) < 1:
        parser.print_help()
        sys.exit(1)

    multi = len(paths) > 1
    for path in paths:
        if multi:
            print(path + ':')
            indent = '   '
        else:
            indent = ''
        if isdir(path):
            lib_dict = tree_libs(path)
            lib_dict = stripped_lib_dict(lib_dict, realpath(getcwd()) + psep)
        else:
            lib_dict = wheel_libs(path)
        keys = sorted(lib_dict)
        if not opts.all:
            keys = [key for key in keys if filter_system_libs(key)]
        if not opts.depending:
            if len(keys):
                print(indent + ('\n' + indent).join(keys))
            continue
        i2 = indent + '    '
        for key in keys:
            print(indent + key + ':')
            libs = lib_dict[key]
            if len(libs):
                print(i2 + ('\n' + i2).join(libs))


if __name__ == '__main__':
    main()

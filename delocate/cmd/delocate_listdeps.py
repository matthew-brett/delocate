#!/usr/bin/env python3
"""List library dependencies for libraries in path or wheel."""

# vim: ft=python

from argparse import ArgumentParser
from os import getcwd
from os.path import isdir, realpath
from os.path import sep as psep

from delocate import wheel_libs
from delocate.cmd.common import common_parser, glob_paths, verbosity_config
from delocate.delocating import filter_system_libs
from delocate.libsana import stripped_lib_dict, tree_libs_from_directory

parser = ArgumentParser(description=__doc__, parents=[common_parser])
parser.add_argument(
    "paths",
    nargs="+",
    metavar="WHEEL_OR_PATH_TO_ANALYZE",
    type=str,
    help="Wheel or directory to check for libraries,"
    " directories are checked recursively",
)
parser.add_argument(
    "-a",
    "--all",
    action="store_true",
    help="Show all dependencies, including system libs",
)
parser.add_argument(
    "-d",
    "--depending",
    action="store_true",
    help="Show libraries depending on dependencies",
)


def main() -> None:  # noqa: D103
    args = parser.parse_args()
    verbosity_config(args)
    paths = list(glob_paths(args.paths))
    multi = len(paths) > 1
    for path in paths:
        if multi:
            print(path + ":")
            indent = "   "
        else:
            indent = ""
        if isdir(path):
            lib_dict = tree_libs_from_directory(path, ignore_missing=True)
            lib_dict = stripped_lib_dict(lib_dict, realpath(getcwd()) + psep)
        else:
            lib_dict = wheel_libs(path, ignore_missing=True)
        keys = sorted(lib_dict)
        if not args.all:
            keys = [key for key in keys if filter_system_libs(key)]
        if not args.depending:
            if len(keys):
                print(indent + ("\n" + indent).join(keys))
            continue
        i2 = indent + "    "
        for key in keys:
            print(indent + key + ":")
            libs = lib_dict[key]
            if len(libs):
                print(i2 + ("\n" + i2).join(libs))


if __name__ == "__main__":
    main()

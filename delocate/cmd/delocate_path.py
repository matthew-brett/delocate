#!/usr/bin/env python3
"""Copy, relink library dependencies for libraries in path."""

# vim: ft=python

import os
from argparse import ArgumentParser

from delocate import delocate_path
from delocate.cmd.common import (
    common_parser,
    delocate_parser,
    delocate_values,
    glob_paths,
    verbosity_config,
)

parser = ArgumentParser(
    description=__doc__, parents=[common_parser, delocate_parser]
)
parser.add_argument(
    "paths",
    nargs="+",
    metavar="PATH",
    type=str,
    help="Folders to be analyzed and delocated",
)
parser.add_argument(
    "-L",
    "--lib-path",
    action="store",
    default=".dylibs",
    type=str,
    help="Output subdirectory path to copy library dependencies",
)


def main() -> None:  # noqa: D103
    args = parser.parse_args()
    verbosity_config(args)
    paths = list(glob_paths(args.paths))
    multi = len(paths) > 1
    for path in paths:
        if multi:
            print(path)
        # evaluate paths relative to the path we are working on
        lib_path = os.path.join(path, args.lib_path)
        delocate_path(
            path,
            lib_path,
            **delocate_values(args),
        )


if __name__ == "__main__":
    main()

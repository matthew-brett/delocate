#!/usr/bin/env python3
""" Copy, relink library dependencies for libraries in path
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

import os
import sys
from optparse import Option, OptionParser

from delocate import __version__, delocate_path
from delocate.cmd.common import (
    delocate_args,
    delocate_values,
    verbosity_args,
    verbosity_config,
)


def main() -> None:
    parser = OptionParser(
        usage="%s PATH_TO_ANALYZE\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__,
    )
    verbosity_args(parser)
    delocate_args(parser)
    parser.add_options(
        [
            Option(
                "-L",
                "--lib-path",
                action="store",
                type="string",
                help="Output subdirectory path to copy library dependencies",
            ),
        ]
    )
    (opts, paths) = parser.parse_args()
    verbosity_config(opts)
    if len(paths) < 1:
        parser.print_help()
        sys.exit(1)

    if opts.lib_path is None:
        opts.lib_path = ".dylibs"
    multi = len(paths) > 1
    for path in paths:
        if multi:
            print(path)
        # evaluate paths relative to the path we are working on
        lib_path = os.path.join(path, opts.lib_path)
        delocate_path(
            path,
            lib_path,
            **delocate_values(opts),
        )


if __name__ == "__main__":
    main()

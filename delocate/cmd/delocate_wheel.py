#!python
""" Copy, relink library dependencies for wheel

Overwrites the wheel in-place by default
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

import os
import sys
from optparse import Option, OptionParser
from os.path import basename, exists, expanduser
from os.path import join as pjoin
from typing import List, Optional, Text

from delocate import __version__, delocate_wheel
from delocate.cmd.common import (
    delocate_args,
    delocate_values,
    verbosity_args,
    verbosity_config,
)


def main() -> None:
    parser = OptionParser(
        usage="%s WHEEL_FILENAME\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__,
    )
    verbosity_args(parser)
    delocate_args(parser)
    parser.add_options(
        [
            Option(
                "-L",
                "--lib-sdir",
                action="store",
                type="string",
                default=".dylibs",
                help="Subdirectory in packages to store copied libraries",
            ),
            Option(
                "-w",
                "--wheel-dir",
                action="store",
                type="string",
                help=(
                    "Directory to store delocated wheels (default is to "
                    "overwrite input)"
                ),
            ),
            Option(
                "-k",
                "--check-archs",
                action="store_true",
                help="Check architectures of depended libraries",
            ),
            Option(
                "--require-archs",
                action="store",
                type="string",
                help=(
                    "Architectures that all wheel libraries should "
                    "have (from 'intel', 'i386', 'x86_64', 'i386,x86_64'"
                    "'universal2', 'x86_64,arm64')"
                ),
            ),
        ]
    )
    (opts, wheels) = parser.parse_args()
    verbosity_config(opts)
    if len(wheels) < 1:
        parser.print_help()
        sys.exit(1)
    multi = len(wheels) > 1
    if opts.wheel_dir:
        wheel_dir = expanduser(opts.wheel_dir)
        if not exists(wheel_dir):
            os.makedirs(wheel_dir)
    else:
        wheel_dir = None
    require_archs: Optional[List[Text]] = None
    if opts.require_archs is None:
        require_archs = [] if opts.check_archs else None
    elif "," in opts.require_archs:
        require_archs = [s.strip() for s in opts.require_archs.split(",")]
    else:
        require_archs = opts.require_archs

    for wheel in wheels:
        if multi or opts.verbose:
            print("Fixing: " + wheel)
        if wheel_dir:
            out_wheel = pjoin(wheel_dir, basename(wheel))
        else:
            out_wheel = wheel
        copied = delocate_wheel(
            wheel,
            out_wheel,
            lib_sdir=opts.lib_sdir,
            require_archs=require_archs,
            **delocate_values(opts),
        )
        if opts.verbose and len(copied):
            print("Copied to package {0} directory:".format(opts.lib_sdir))
            copy_lines = ["  " + name for name in sorted(copied)]
            print("\n".join(copy_lines))


if __name__ == "__main__":
    main()

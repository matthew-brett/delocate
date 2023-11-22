#!python
""" Fuse two (probably delocated) wheels

Overwrites the first wheel in-place by default
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

import sys
from optparse import Option, OptionParser
from os.path import abspath, basename, expanduser
from os.path import join as pjoin

from delocate import __version__
from delocate.cmd.common import verbosity_args, verbosity_config
from delocate.fuse import fuse_wheels


def main() -> None:
    parser = OptionParser(
        usage="%s WHEEL1 WHEEL2\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__,
    )
    verbosity_args(parser)
    parser.add_option(
        Option(
            "-w",
            "--wheel-dir",
            action="store",
            type="string",
            help=(
                "Directory to store delocated wheels (default is to "
                "overwrite WHEEL1 input)"
            ),
        )
    )
    (opts, wheels) = parser.parse_args()
    verbosity_config(opts)
    if len(wheels) != 2:
        parser.print_help()
        sys.exit(1)
    wheel1, wheel2 = [abspath(expanduser(wheel)) for wheel in wheels]
    if opts.wheel_dir is None:
        out_wheel = wheel1
    else:
        out_wheel = pjoin(abspath(expanduser(opts.wheel_dir)), basename(wheel1))
    fuse_wheels(wheel1, wheel2, out_wheel)


if __name__ == "__main__":
    main()

#!python
""" Apply patch to tree stored in wheel

Overwrites the wheel in-place by default
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

import os
import sys
from optparse import Option, OptionParser
from os.path import basename, exists, expanduser
from os.path import join as pjoin

from delocate import __version__, patch_wheel
from delocate.cmd.common import verbosity_args, verbosity_config


def main() -> None:
    parser = OptionParser(
        usage="%s WHEEL_FILENAME PATCH_FNAME\n\n" % sys.argv[0] + __doc__,
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
                "Directory to store patched wheel (default is to "
                "overwrite input)"
            ),
        )
    )
    (opts, args) = parser.parse_args()
    verbosity_config(opts)
    if len(args) != 2:
        parser.print_help()
        sys.exit(1)
    wheel, patch_fname = args
    if opts.wheel_dir:
        wheel_dir = expanduser(opts.wheel_dir)
        if not exists(wheel_dir):
            os.makedirs(wheel_dir)
    else:
        wheel_dir = None
    if opts.verbose:
        print("Patching: {0} with {1}".format(wheel, patch_fname))
    if wheel_dir:
        out_wheel = pjoin(wheel_dir, basename(wheel))
    else:
        out_wheel = wheel
    patch_wheel(wheel, patch_fname, out_wheel)
    if opts.verbose:
        print("Patched wheel {0} to {1}:".format(wheel, out_wheel))


if __name__ == "__main__":
    main()

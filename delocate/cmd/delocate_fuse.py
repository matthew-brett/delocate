#!/usr/bin/env python3
""" Fuse two (probably delocated) wheels

Overwrites the first wheel in-place by default
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

from argparse import ArgumentParser
from os.path import abspath, basename, expanduser
from os.path import join as pjoin

from delocate.cmd.common import common_parser, verbosity_config
from delocate.fuse import fuse_wheels

parser = ArgumentParser(description=__doc__, parents=[common_parser])
parser.add_argument(
    "wheels", nargs=2, metavar="WHEEL", type=str, help="Wheels to fuse"
)
parser.add_argument(
    "-w",
    "--wheel-dir",
    action="store",
    type=str,
    help="Directory to store delocated wheels"
    " (default is to overwrite 1st WHEEL input with 2nd)",
)


def main() -> None:
    args = parser.parse_args()
    verbosity_config(args)
    wheel1, wheel2 = [abspath(expanduser(wheel)) for wheel in args.wheels]
    if args.wheel_dir is None:
        out_wheel = wheel1
    else:
        out_wheel = pjoin(abspath(expanduser(args.wheel_dir)), basename(wheel1))
    fuse_wheels(wheel1, wheel2, out_wheel)


if __name__ == "__main__":
    main()

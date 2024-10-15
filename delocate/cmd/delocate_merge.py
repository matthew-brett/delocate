#!/usr/bin/env python3
"""Fuse two (probably delocated) wheels.

Writes to a new wheel with an automatically determined name by default.
"""

# vim: ft=python
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

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
    " (default is to store in the same directory as the 1st WHEEL with an"
    " automatically determined name).",
)


def main() -> None:  # noqa: D103
    args = parser.parse_args()
    verbosity_config(args)
    wheel1, wheel2 = (Path(wheel).resolve(strict=True) for wheel in args.wheels)
    out_wheel = Path(
        args.wheel_dir if args.wheel_dir is not None else wheel1.parent
    ).resolve()
    out_wheel.mkdir(parents=True, exist_ok=True)
    fuse_wheels(wheel1, wheel2, out_wheel)


if __name__ == "__main__":
    main()

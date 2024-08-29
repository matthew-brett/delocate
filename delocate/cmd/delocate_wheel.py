#!/usr/bin/env python3
"""Copy, relink library dependencies for wheel.

Overwrites the wheel in-place by default.

This script respects the MACOSX_DEPLOYMENT_TARGET environment variable.
Set MACOSX_DEPLOYMENT_TARGET to verify and target a specific macOS release.
"""

# vim: ft=python
from __future__ import annotations

import os
from argparse import ArgumentParser
from os.path import basename, exists, expanduser
from os.path import join as pjoin

from packaging.version import Version

from delocate import delocate_wheel
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
    "wheels",
    nargs="+",
    metavar="WHEEL",
    type=str,
    help="The wheel files to be delocated",
)
parser.add_argument(
    "-L",
    "--lib-sdir",
    action="store",
    type=str,
    default=".dylibs",
    help="Subdirectory in packages to store copied libraries"
    "\nFor non-package wheels this will be used as a suffix for the library "
    "directory",
)
parser.add_argument(
    "-w",
    "--wheel-dir",
    action="store",
    type=str,
    help="Directory to store delocated wheels (default is to overwrite input)",
)
parser.add_argument(
    "-k",
    "--check-archs",
    action="store_true",
    help="Check architectures of depended libraries",
)
parser.add_argument(
    "--require-archs",
    metavar="ARCHITECTURES",
    action="store",
    type=str,
    help="Architectures that all wheel libraries should have"
    " (from 'intel', 'i386', 'x86_64', 'i386,x86_64', 'universal2',"
    " 'x86_64,arm64')",
)
parser.add_argument(
    "--require-target-macos-version",
    type=Version,
    help="Verify if platform tag in wheel name is proper (deprecated)"
    "\nConfigure MACOSX_DEPLOYMENT_TARGET instead of using this flag",
    default=None,
)


def main() -> None:  # noqa: D103
    args = parser.parse_args()
    verbosity_config(args)
    wheels = list(glob_paths(args.wheels))
    multi = len(wheels) > 1
    if args.wheel_dir:
        wheel_dir = expanduser(args.wheel_dir)
        if not exists(wheel_dir):
            os.makedirs(wheel_dir)
    else:
        wheel_dir = None
    require_archs: list[str] | None = None
    if args.require_archs is None:
        require_archs = [] if args.check_archs else None
    elif "," in args.require_archs:
        require_archs = [s.strip() for s in args.require_archs.split(",")]
    else:
        require_archs = args.require_archs

    require_target_macos_version = args.require_target_macos_version
    if (
        require_target_macos_version is None
        and "MACOSX_DEPLOYMENT_TARGET" in os.environ
    ):
        require_target_macos_version = Version(
            os.environ["MACOSX_DEPLOYMENT_TARGET"]
        )

    for wheel in wheels:
        if multi or args.verbose:
            print("Fixing: " + wheel)
        if wheel_dir:
            out_wheel = pjoin(wheel_dir, basename(wheel))
        else:
            out_wheel = wheel
        copied = delocate_wheel(
            wheel,
            out_wheel,
            lib_sdir=args.lib_sdir,
            require_archs=require_archs,
            require_target_macos_version=require_target_macos_version,
            **delocate_values(args),
        )
        if args.verbose and len(copied):
            print(f"Copied to package {args.lib_sdir} directory:")
            copy_lines = ["  " + name for name in sorted(copied)]
            print("\n".join(copy_lines))


if __name__ == "__main__":
    main()

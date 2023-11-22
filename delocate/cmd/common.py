""" Code shared among multiple commands.

All functions in this module are private.
"""
from __future__ import annotations

import logging
import os
import sys
from optparse import Option, OptionParser, Values
from typing import Callable, List

from delocate.delocating import filter_system_libs
from typing_extensions import Literal, TypedDict

logger = logging.getLogger(__name__)


def verbosity_args(parser: OptionParser) -> None:
    """Logging arguments shared by all commands."""
    parser.add_options(
        [
            Option(
                "-v",
                "--verbose",
                action="count",
                help=(
                    "Show a more verbose report of progress and failure."
                    "  Additional flags show even more info, up to -vv."
                ),
                default=0,
            ),
        ]
    )


def verbosity_config(opts: Values) -> None:
    """Configure logging from parsed verbosity arguments."""
    logging.basicConfig(
        level={0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(
            opts.verbose, logging.DEBUG
        )
    )


def delocate_args(parser: OptionParser):
    """Arguments shared by delocate-path and delocate-wheel commands."""
    parser.add_options(
        [
            Option(
                "-d",
                "--dylibs-only",
                action="store_true",
                help="Only analyze files with known dynamic library extensions",
            ),
            Option(
                "-e",
                "--exclude",
                action="append",
                default=[],
                type="string",
                help=(
                    "Exclude any libraries where path includes the given string"
                ),
            ),
            Option(
                "--executable-path",
                action="store",
                type="string",
                default=os.path.dirname(sys.executable),
                help=(
                    "The path used to resolve @executable_path in dependencies"
                ),
            ),
            Option(
                "--ignore-missing-dependencies",
                action="store_true",
                help=(
                    "Skip dependencies which couldn't be found and delocate "
                    "as much as possible"
                ),
            ),
        ]
    )


class DelocateArgs(TypedDict):
    """Common kwargs for delocate_path and delocate_wheel."""

    copy_filt_func: Callable[[str], bool]
    executable_path: str
    lib_filt_func: Callable[[str], bool] | Literal["dylibs-only"] | None
    ignore_missing: bool


def delocate_values(opts: Values) -> DelocateArgs:
    """Return the common kwargs for delocate_path and delocate_wheel."""

    exclude_files: List[str] = opts.exclude

    def copy_filter_exclude(name: str) -> bool:
        """Returns False if name is excluded, uses normal rules otherwise."""
        for exclude_str in exclude_files:
            if exclude_str in name:
                logger.info(
                    "%s excluded because of exclude %r rule.",
                    name,
                    exclude_str,
                )
                return False
        return filter_system_libs(name)

    return {
        "copy_filt_func": copy_filter_exclude,
        "executable_path": opts.executable_path,
        "lib_filt_func": "dylibs-only" if opts.dylibs_only else None,
        "ignore_missing": opts.ignore_missing_dependencies,
    }

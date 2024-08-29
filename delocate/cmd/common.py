"""Code shared among multiple commands.

All functions in this module are private.
"""

from __future__ import annotations

import glob
import logging
import os
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Callable

from typing_extensions import Literal, TypedDict

from delocate import __version__
from delocate.delocating import filter_system_libs

logger = logging.getLogger(__name__)


common_parser = ArgumentParser(add_help=False)
"""Version and logging arguments shared by all commands."""

common_parser.add_argument(
    "--version", action="version", version=f"%(prog)s {__version__}"
)
common_parser.add_argument(
    "-v",
    "--verbose",
    action="count",
    help="Show a more verbose report of progress and failure,"
    " additional flags show even more info, up to -vv",
    default=0,
)


delocate_parser = ArgumentParser(add_help=False)
"""Arguments shared by delocate-path and delocate-wheel commands."""

delocate_parser.add_argument(
    "-d",
    "--dylibs-only",
    action="store_true",
    help="Only analyze files with known dynamic library extensions",
)
delocate_parser.add_argument(
    "-e",
    "--exclude",
    action="append",
    default=[],
    type=str,
    help="Exclude any libraries where path includes the given string",
)
delocate_parser.add_argument(
    "--executable-path",
    action="store",
    type=str,
    default=os.path.dirname(sys.executable),
    help="The path used to resolve @executable_path in dependencies",
)
delocate_parser.add_argument(
    "--ignore-missing-dependencies",
    action="store_true",
    help="Skip dependencies which couldn't be found and delocate"
    " as much as possible",
)
delocate_parser.add_argument(
    "--sanitize-rpaths",
    action="store_true",
    default=True,
    help="Remove absolute and relative rpaths from binaries (default)",
)
delocate_parser.add_argument(
    "--no-sanitize-rpaths",
    action="store_false",
    dest="sanitize_rpaths",
    help="Don't remove absolute and relative rpaths from binaries",
)


def verbosity_config(args: Namespace) -> None:
    """Configure logging from parsed verbosity arguments."""
    logging.basicConfig(
        level={0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(
            args.verbose, logging.DEBUG
        )
    )


class DelocateArgs(TypedDict):
    """Common kwargs for delocate_path and delocate_wheel."""

    copy_filt_func: Callable[[str], bool]
    executable_path: str
    lib_filt_func: Callable[[str], bool] | Literal["dylibs-only"] | None
    ignore_missing: bool
    sanitize_rpaths: bool


def delocate_values(args: Namespace) -> DelocateArgs:
    """Return the common kwargs for delocate_path and delocate_wheel."""
    exclude_files: list[str] = args.exclude

    def copy_filter_exclude(name: str) -> bool:
        """Return False if name is excluded, uses normal rules otherwise."""
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
        "executable_path": args.executable_path,
        "lib_filt_func": "dylibs-only" if args.dylibs_only else None,
        "ignore_missing": args.ignore_missing_dependencies,
        "sanitize_rpaths": args.sanitize_rpaths,
    }


def glob_paths(paths: Iterable[str]) -> Iterator[str]:
    """Iterate over the expanded paths of potential glob paths.

    Does not try to glob paths which match existing files.
    """
    for path in paths:
        if Path(path).exists():
            yield path  # Don't try to expand paths when their target exists
            continue
        expanded_paths = glob.glob(path)
        if not expanded_paths:
            raise FileNotFoundError(path)
        yield from expanded_paths

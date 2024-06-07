#!/usr/bin/env python3
"""Fuse two (probably delocated) wheels.

Command is no longer available. To fuse two wheels together use
'delocate-merge'. NOTE: 'delocate-merge' does not overwrite the first wheel. It
creates a new wheel with an automatically determined name. If the old behavior
is needed (not recommended), pin the version to 'delocate==0.11.0'.
"""

# vim: ft=python
from __future__ import annotations


def main() -> None:  # noqa: D103
    print(
        "'delocate-fuse' is no longer available. To fuse two wheels together"
        " use 'delocate-merge'. NOTE: 'delocate-merge' does not overwrite the"
        " first wheel. It creates a new wheel with an automatically determined"
        " name. If the old behavior is needed (not recommended), pin the"
        " version to 'delocate==0.11.0'."
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()

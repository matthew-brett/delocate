#!python
""" Fuse two (probably delocated) wheels

Overwrites the first wheel in-place by default
"""
# vim: ft=python
from __future__ import division, print_function, absolute_import

from os.path import (join as pjoin, basename, expanduser, abspath)
import sys

from optparse import OptionParser, Option

from delocate import __version__
from delocate.fuse import fuse_wheels


def main():
    parser = OptionParser(
        usage="%s WHEEL1 WHEEL2\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__)
    parser.add_option(
        Option("-w", "--wheel-dir",
               action="store", type='string',
               help="Directory to store delocated wheels (default is to "
               "overwrite WHEEL1 input)"))
    parser.add_option(
        Option("-v", "--verbose",
               action="store_true",
               help="Show libraries copied during fix"))
    (opts, wheels) = parser.parse_args()
    if len(wheels) != 2:
        parser.print_help()
        sys.exit(1)
    wheel1, wheel2 = [abspath(expanduser(wheel)) for wheel in wheels]
    if opts.wheel_dir is None:
        out_wheel = wheel1
    else:
        out_wheel = pjoin(abspath(expanduser(opts.wheel_dir)),
                          basename(wheel1))
    fuse_wheels(wheel1, wheel2, out_wheel)


if __name__ == '__main__':
    main()

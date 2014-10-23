#!python
""" Add platform tags to wheel filename(s) and WHEEL file in wheel

Example:

    delocate-addplat -p macosx_10_9_intel -p macosx_10_9_x86_64 *.whl

or (same result):

    delocate-addplat -x 10_9 *.whl

or (adds tags for OSX 10.9 and 10.10):

    delocate-addplat -x 10_9 -x 10_10 *.whl
"""
# vim: ft=python
from __future__ import division, print_function, absolute_import

import sys
import os
from os.path import join as exists, expanduser, realpath
from optparse import OptionParser, Option

from delocate import __version__
from delocate.wheeltools import add_platforms, WheelToolsError


def main():
    parser = OptionParser(
        usage="%s WHEEL_FILENAME\n\n" % sys.argv[0] + __doc__,
        version="%prog " + __version__)
    parser.add_option(
        Option("-p", "--plat-tag", action="append", type='string',
               help="Platform tag to add (e.g. macosx_10_9_intel) (can be "
               "specified multiple times)"))
    parser.add_option(
        Option("-x", "--osx-ver", action="append", type='string',
               help='Alternative method to specify platform tags, by giving '
               'OSX version numbers - e.g. "10_10" results in adding platform '
               'tags "macosx_10_10_intel, "macosx_10_10_x86_64") (can be '
               "specified multiple times)"))
    parser.add_option(
        Option("-w", "--wheel-dir",
               action="store", type='string',
               help="Directory to store delocated wheels (default is to "
               "overwrite input)"))
    parser.add_option(
        Option("-c", "--clobber",
               action="store_true",
               help="Overwrite pre-existing wheels"))
    parser.add_option(
        Option("-r", "--rm-orig",
               action="store_true",
               help="Remove unmodified wheel if wheel is rewritten"))
    parser.add_option(
        Option("-k", "--skip-errors",
               action="store_true",
               help="Skip wheels that raise errors (e.g. pure wheels)"))
    parser.add_option(
        Option("-v", "--verbose",
               action="store_true",
               help="Show more verbose report of progress and failure"))
    (opts, wheels) = parser.parse_args()
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
    plat_tags = [] if opts.plat_tag is None else opts.plat_tag
    if not opts.osx_ver is None:
        for ver in opts.osx_ver:
            plat_tags += ['macosx_{0}_intel'.format(ver),
                          'macosx_{0}_x86_64'.format(ver)]
    if len(plat_tags) == 0:
        raise RuntimeError('Need at least one --osx-ver or --plat-tag')
    for wheel in wheels:
        if multi or opts.verbose:
            print('Setting platform tags {0} for wheel {1}'.format(
                ','.join(plat_tags), wheel))
        try:
            fname = add_platforms(wheel, plat_tags, wheel_dir,
                                  clobber=opts.clobber)
        except WheelToolsError as e:
            if opts.skip_errors:
                print("Cannot modify {0} because {1}".format(wheel, e))
                continue
            raise
        if opts.verbose:
            if fname is None:
                print('{0} already has tags {1}'.format(
                    wheel, ', '.join(plat_tags)))
            else:
                print("Wrote {0}".format(fname))
        if (opts.rm_orig and not fname is None
            and realpath(fname) != realpath(wheel)):
            os.unlink(wheel)
            if opts.verbose:
                print("Deleted old wheel " + wheel)


if __name__ == '__main__':
    main()

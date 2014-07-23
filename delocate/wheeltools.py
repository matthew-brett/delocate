""" General tools for working with wheels

Tools that aren't specific to delocation
"""

import os
from os.path import join as pjoin, abspath, relpath, exists, sep as psep
import glob
import hashlib
import csv

from wheel.util import urlsafe_b64encode, open_for_csv, native

from .tmpdirs import InTemporaryDirectory
from .tools import zip2dir, dir2zip

class WheelToolsError(Exception):
    pass


def rewrite_record(bdist_dir):
    """ Rewrite RECORD file with hashes for all files in `wheel_sdir`

    Copied from :method:`wheel.bdist_wheel.bdist_wheel.write_record`

    Will also unsign wheel

    Parameters
    ----------
    bdist_dir : str
        Path of unpacked wheel file
    """
    info_dirs = glob.glob(pjoin(bdist_dir, '*.dist-info'))
    if len(info_dirs) != 1:
        raise WheelToolsError("Should be exactly one `*.dist_info` directory")
    record_path = pjoin(info_dirs[0], 'RECORD')
    record_relpath = relpath(record_path, bdist_dir)
    # Unsign wheel - because we're invalidating the record hash
    sig_path = pjoin(info_dirs[0], 'RECORD.jws')
    if exists(sig_path):
        os.unlink(sig_path)

    def walk():
        for dir, dirs, files in os.walk(bdist_dir):
            for f in files:
                yield pjoin(dir, f)

    def skip(path):
        """Wheel hashes every possible file."""
        return (path == record_relpath)

    with open_for_csv(record_path, 'w+') as record_file:
        writer = csv.writer(record_file)
        for path in walk():
            relative_path = relpath(path, bdist_dir)
            if skip(relative_path):
                hash = ''
                size = ''
            else:
                with open(path, 'rb') as f:
                    data = f.read()
                digest = hashlib.sha256(data).digest()
                hash = 'sha256=' + native(urlsafe_b64encode(digest))
                size = len(data)
            record_path = relpath(
                path, bdist_dir).replace(psep, '/')
            writer.writerow((record_path, hash, size))


class InWheel(InTemporaryDirectory):
    """ Context manager for doing things inside wheels

    On entering, you'll find yourself in the root tree of the wheel.  If you've
    asked for an output wheel, then on exit we'll rewrite the wheel record and
    pack stuff up for you.
    """
    def __init__(self, in_wheel, out_wheel=None):
        """ Initialize in-wheel context manager

        Parameters
        ----------
        in_wheel : str
            filename of wheel to unpack and work inside
        out_wheel : None or str:
            filename of wheel to write after exiting.  If None, don't write and
            discard
        """
        self.in_wheel = abspath(in_wheel)
        self.out_wheel = None if out_wheel is None else abspath(out_wheel)
        super(InWheel, self).__init__()

    def __enter__(self):
        zip2dir(self.in_wheel, self.name)
        return super(InWheel, self).__enter__()

    def __exit__(self, exc, value, tb):
        if not self.out_wheel is None:
            rewrite_record(self.name)
            dir2zip(self.name, self.out_wheel)
        return super(InWheel, self).__exit__(exc, value, tb)

"""Test tmpdirs module."""

from os import getcwd
from os.path import abspath, dirname, isfile, realpath

from ..tmpdirs import InGivenDirectory
from .pytest_tools import assert_equal, assert_true

MY_PATH = abspath(__file__)
MY_DIR = dirname(MY_PATH)


def test_given_directory():
    # Test InGivenDirectory
    cwd = getcwd()
    with InGivenDirectory() as tmpdir:
        assert_equal(tmpdir, abspath(cwd))
        assert_equal(tmpdir, abspath(getcwd()))
    with InGivenDirectory(MY_DIR) as tmpdir:
        assert_equal(tmpdir, MY_DIR)
        assert_equal(realpath(MY_DIR), realpath(abspath(getcwd())))
    # We were deleting the Given directory!  Check not so now.
    assert_true(isfile(MY_PATH))

"""Test shared command-line helpers."""

import pytest

from ..cmd.common import glob_paths


def test_glob_paths_existing_file(tmp_path):
    target = tmp_path / "libfoo.dylib"
    target.write_bytes(b"fake")
    assert list(glob_paths([str(target)])) == [str(target)]


def test_glob_paths_missing_file():
    with pytest.raises(FileNotFoundError):
        list(glob_paths(["no-such-library-xyz"]))


def test_glob_paths_empty_string():
    # An empty path must not slip past the missing-file guard (`Path('')`
    # normalizes to the current directory, which always exists).
    with pytest.raises(FileNotFoundError):
        list(glob_paths([""]))

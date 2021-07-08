import os
import pytest

@pytest.fixture
def in_tmpdir(tmp_path):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


def test_something(in_tmpdir):
    print('tmpdir', os.getcwd())


def test_something_else():
    print('not tmpdir', os.getcwd())

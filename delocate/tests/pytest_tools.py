import os

import pytest


def assert_true(condition):
    __tracebackhide__ = True
    assert condition


def assert_false(condition):
    __tracebackhide__ = True
    assert not condition


def assert_raises(expected_exception, *args, **kwargs):
    __tracebackhide__ = True
    return pytest.raises(expected_exception, *args, **kwargs)


def assert_equal(first, second):
    __tracebackhide__ = True
    assert first == second


def assert_not_equal(first, second):
    __tracebackhide__ = True
    assert first != second


@pytest.fixture
def in_tmp_path(tmp_path):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)

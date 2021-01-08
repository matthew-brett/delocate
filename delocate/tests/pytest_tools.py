from typing import Any

import pytest


def assert_true(condition):
    # type: (Any) -> None
    __tracebackhide__ = True
    assert condition


def assert_false(condition):
    # type: (Any) -> None
    __tracebackhide__ = True
    assert not condition


def assert_raises(expected_exception, *args, **kwargs):
    # type: (Any, *Any, **Any) -> Any
    __tracebackhide__ = True
    return pytest.raises(expected_exception, *args, **kwargs)


def assert_equal(first, second):
    # type: (Any, Any) -> None
    __tracebackhide__ = True
    assert first == second


def assert_not_equal(first, second):
    # type: (Any, Any) -> None
    __tracebackhide__ = True
    assert first != second

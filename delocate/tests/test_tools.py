""" Test tools module """
from __future__ import division, print_function

from ..tools import back_tick

from nose.tools import assert_true, assert_false, assert_equal, assert_raises


def test_back_tick():
    cmd = 'python -c "print(\'Hello\')"'
    assert_equal(back_tick(cmd), "Hello")
    assert_equal(back_tick(cmd, ret_err=True), ("Hello", ""))
    assert_equal(back_tick(cmd, True, False), (b"Hello", b""))
    cmd = 'python -c "raise ValueError()"'
    assert_raises(RuntimeError, back_tick, cmd)

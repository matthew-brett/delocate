from delocate.tests.pytest_tools import (assert_true, assert_false, assert_raises,
                        assert_equal, assert_not_equal)


from ..module1 import func1
from ..subpkg.module2 import func2, func3


def test_fakepkg():
    assert_equal(func1(), 1)
    assert_equal(func2(), 2)
    assert_equal(func3(), 3)

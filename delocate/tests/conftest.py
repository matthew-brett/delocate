import os
from pathlib import Path
from typing import Iterator

import pytest
from delocate.tools import set_install_name
from delocate.wheeltools import InWheelCtx

from .test_wheelies import PLAT_WHEEL, STRAY_LIB_DEP, PlatWheel


@pytest.fixture
def plat_wheel(tmp_path: Path) -> Iterator[PlatWheel]:
    """Return a modified platform wheel for testing."""
    plat_wheel_tmp = str(tmp_path / "plat-wheel.whl")
    stray_lib: str = STRAY_LIB_DEP

    with InWheelCtx(PLAT_WHEEL, plat_wheel_tmp):
        set_install_name(
            "fakepkg1/subpkg/module2.abi3.so",
            "libextfunc.dylib",
            stray_lib,
        )

    yield PlatWheel(plat_wheel_tmp, os.path.realpath(stray_lib))

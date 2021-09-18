# Init for delocate package

from .delocating import delocate_path, delocate_wheel, patch_wheel
from .libsana import tree_libs, wheel_libs

from ._version import get_versions
__version__ = get_versions()['version']  # type: ignore
del get_versions

__all__ = ("delocate_path", "delocate_wheel", "patch_wheel", "tree_libs",
           "wheel_libs", "__version__")

from . import _version
__version__ = _version.get_versions()['version']

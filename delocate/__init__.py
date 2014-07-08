# Init for delocate package

from .delocating import delocate_path, delocate_wheel, patch_wheel
from .libsana import tree_libs, wheel_libs

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

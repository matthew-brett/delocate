# Init for delocate package

from .delocator import delocate_path, delocate_wheel
from .tools import tree_libs

from ._version import get_versions
__version__ = get_versions()['version']
del get_versions

"""Delocate package."""

import warnings

from .delocating import delocate_path, delocate_wheel, patch_wheel
from .libsana import tree_libs, wheel_libs

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.0.0"
    warnings.warn(
        "Delocate was not installed and is missing version metadata."
        "\nMake sure this package is installed in development mode"
        " with this command:\n\tpip install --editable .",
        RuntimeWarning,
    )

__all__ = (
    "delocate_path",
    "delocate_wheel",
    "patch_wheel",
    "tree_libs",
    "wheel_libs",
    "__version__",
)

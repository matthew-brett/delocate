"""Setup for fakepkg1.

fakepkg2 is a - fake package - with Python only. We use it to build a wheel,
then test we can delocate it.
"""

from setuptools import setup

setup(
    name="fakepkg2",
    version="1.0",
    packages=["fakepkg2", "fakepkg2.subpkg", "fakepkg2.tests"],
)

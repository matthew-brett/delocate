#!/usr/bin/env python3
"""Setup script for delocate package."""

from os.path import join as pjoin

from setuptools import find_packages, setup

setup(
    packages=find_packages(),
    package_data={
        "delocate.tests": [
            pjoin("data", "*.dylib"),
            pjoin("data", "*.txt"),
            pjoin("data", "*.bin"),
            pjoin("data", "*.py"),
            pjoin("data", "liba.a"),
            pjoin("data", "a.o"),
            pjoin("data", "*.whl"),
            pjoin("data", "test-lib"),
            pjoin("data", "*patch"),
            pjoin("data", "make_libs.sh"),
            pjoin("data", "icon.ico"),
        ],
        "delocate": ["py.typed"],
    },
)

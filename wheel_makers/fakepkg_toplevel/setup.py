"""Setup package with an extension linked to an external library."""

import subprocess
from pathlib import Path

from setuptools import Extension, setup  # type: ignore

HERE = Path(__file__).parent.resolve(strict=True)
LIBS = HERE / "libs"
ARCH_FLAGS = ["-arch", "arm64", "-arch", "x86_64"]  # Dual architecture.

subprocess.run(
    [
        "cc",
        str(LIBS / "extfunc2.c"),
        "-dynamiclib",
        "-install_name",
        "@rpath/libextfunc2_rpath.dylib",
        "-o",
        str(LIBS / "libextfunc2_rpath.dylib"),
    ]
    + ARCH_FLAGS,
    check=True,
)

ext_modules = [
    Extension(
        "module2",
        ["module2.c"],
        libraries=["extfunc2_rpath"],
        extra_compile_args=ARCH_FLAGS,
        extra_link_args=[f"-L{LIBS}", "-rpath", "libs/"],
        py_limited_api=True,
    )
]

setup(
    ext_modules=ext_modules,
    name="fakepkg_toplevel",
    version="1.0",
    py_modules=["module2", "test_fakepkg_toplevel"],
)

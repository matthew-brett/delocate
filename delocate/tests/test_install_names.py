""" Tests for install name utilities """

import contextlib
import os
import shutil
import sys
from os.path import basename, dirname, exists
from os.path import join as pjoin
from subprocess import CompletedProcess
from typing import (
    ContextManager,
    Dict,
    NamedTuple,
    Sequence,
    Tuple,
    Type,
    Union,
)
from unittest import mock

import pytest

from ..tmpdirs import InTemporaryDirectory
from ..tools import (
    InstallNameError,
    add_rpath,
    get_environment_variable_paths,
    get_install_id,
    get_install_names,
    get_rpaths,
    parse_install_name,
    set_install_id,
    set_install_name,
)
from .env_tools import TempDirWithoutEnvVars
from .pytest_tools import assert_equal, assert_raises

# External libs linked from test data
LIBSTDCXX = "/usr/lib/libc++.1.dylib"
LIBSYSTEMB = "/usr/lib/libSystem.B.dylib"
EXT_LIBS = (LIBSTDCXX, LIBSYSTEMB)

DATA_PATH = pjoin(dirname(__file__), "data")
LIBA = pjoin(DATA_PATH, "liba.dylib")
LIBB = pjoin(DATA_PATH, "libb.dylib")
LIBC = pjoin(DATA_PATH, "libc.dylib")
LIBAM1_ARCH = pjoin(DATA_PATH, "libam1-arch.dylib")
LIBA_STATIC = pjoin(DATA_PATH, "liba.a")
A_OBJECT = pjoin(DATA_PATH, "a.o")
TEST_LIB = pjoin(DATA_PATH, "test-lib")
ICO_FILE = pjoin(DATA_PATH, "icon.ico")
PY_FILE = pjoin(DATA_PATH, "some_code.py")
BIN_FILE = pjoin(DATA_PATH, "binary_example.bin")


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_get_install_names() -> None:
    # Test install name listing
    assert set(get_install_names(LIBA)) == set(EXT_LIBS)
    assert set(get_install_names(LIBB)) == set(("liba.dylib",) + EXT_LIBS)
    assert set(get_install_names(LIBC)) == set(
        ("liba.dylib", "libb.dylib") + EXT_LIBS
    )
    assert set(get_install_names(TEST_LIB)) == set(("libc.dylib",) + EXT_LIBS)
    assert set(get_install_names(LIBAM1_ARCH)) == set(EXT_LIBS)
    # Non-object file returns empty tuple
    assert get_install_names(__file__) == ()
    # Static archive and object files returns empty tuple
    assert get_install_names(A_OBJECT) == ()
    assert get_install_names(LIBA_STATIC) == ()
    # ico file triggers another error message and should also return an empty tuple  # noqa: E501
    assert get_install_names(ICO_FILE) == ()
    # Python file (__file__ above may be a pyc file)
    assert get_install_names(PY_FILE) == ()
    # Binary file (in fact a truncated SAS file)
    assert get_install_names(BIN_FILE) == ()
    # Test when no read permission
    with InTemporaryDirectory():
        shutil.copyfile(LIBA, "test.dylib")
        assert set(get_install_names("test.dylib")) == set(EXT_LIBS)
        # No permissions, no found libs
        os.chmod("test.dylib", 0)
        assert get_install_names("test.dylib") == ()


def test_parse_install_name():
    assert_equal(
        parse_install_name(
            "liba.dylib (compatibility version 0.0.0, current version 0.0.0)"
        ),
        ("liba.dylib", "0.0.0", "0.0.0"),
    )
    assert_equal(
        parse_install_name(
            " /usr/lib/libstdc++.6.dylib (compatibility version 1.0.0, "
            "current version 120.0.0)"
        ),
        ("/usr/lib/libstdc++.6.dylib", "1.0.0", "120.0.0"),
    )
    assert_equal(
        parse_install_name(
            "\t\t   /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, "
            "current version 1197.1.1)"
        ),
        ("/usr/lib/libSystem.B.dylib", "1.0.0", "1197.1.1"),
    )


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_install_id():
    # Test basic otool library listing
    assert_equal(get_install_id(LIBA), "liba.dylib")
    assert_equal(get_install_id(LIBB), "libb.dylib")
    assert_equal(get_install_id(LIBC), "libc.dylib")
    assert_equal(get_install_id(TEST_LIB), None)
    # Non-object file returns None too
    assert_equal(get_install_id(__file__), None)
    assert_equal(get_install_id(ICO_FILE), None)


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_change_install_name():
    # Test ability to change install names in library
    libb_names = get_install_names(LIBB)
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, "libfoo.dylib")
        shutil.copy2(LIBB, libfoo)
        assert_equal(get_install_names(libfoo), libb_names)
        set_install_name(libfoo, "liba.dylib", "libbar.dylib")
        assert_equal(
            get_install_names(libfoo), ("libbar.dylib",) + libb_names[1:]
        )
        # If the name not found, raise an error
        assert_raises(
            InstallNameError,
            set_install_name,
            libfoo,
            "liba.dylib",
            "libpho.dylib",
        )


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_set_install_id():
    # Test ability to change install id in library
    liba_id = get_install_id(LIBA)
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, "libfoo.dylib")
        shutil.copy2(LIBA, libfoo)
        assert_equal(get_install_id(libfoo), liba_id)
        set_install_id(libfoo, "libbar.dylib")
        assert_equal(get_install_id(libfoo), "libbar.dylib")
    # If no install id, raise error (unlike install_name_tool)
    assert_raises(InstallNameError, set_install_id, TEST_LIB, "libbof.dylib")


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_get_rpaths() -> None:
    # Test fetch of rpaths
    # Not dynamic libs, no rpaths
    for fname in (LIBB, A_OBJECT, LIBA_STATIC, ICO_FILE, PY_FILE, BIN_FILE):
        assert get_rpaths(fname) == ()


def test_get_environment_variable_paths():
    # Test that environment variable paths are fetched in a specific order
    with TempDirWithoutEnvVars(
        "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_LIBRARY_PATH"
    ):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "three"
        os.environ["DYLD_LIBRARY_PATH"] = "two"
        assert_equal(get_environment_variable_paths(), ("two", "three"))


@pytest.mark.xfail(sys.platform != "darwin", reason="otool")
def test_add_rpath():
    # Test adding to rpath
    with InTemporaryDirectory() as tmpdir:
        libfoo = pjoin(tmpdir, "libfoo.dylib")
        shutil.copy2(LIBB, libfoo)
        assert_equal(get_rpaths(libfoo), ())
        add_rpath(libfoo, "/a/path")
        assert_equal(get_rpaths(libfoo), ("/a/path",))
        add_rpath(libfoo, "/another/path")
        assert_equal(get_rpaths(libfoo), ("/a/path", "/another/path"))


def _copy_libs(lib_files, out_path):
    copied = []
    if not exists(out_path):
        os.makedirs(out_path)
    for in_fname in lib_files:
        out_fname = pjoin(out_path, basename(in_fname))
        shutil.copy2(in_fname, out_fname)
        copied.append(out_fname)
    return copied


def assert_raises_if_exception(
    exception: object,
) -> ContextManager[object]:
    """Returns a pytest.raises context if `exception` is an Exception type."""
    if isinstance(exception, type) and issubclass(exception, Exception):
        return pytest.raises(exception)
    return contextlib.nullcontext()


class ToolArchMock(NamedTuple):
    """A group of expectations and mocks for otool-based function tests."""

    commands: Dict[Tuple[str, ...], str]  # {command: stdout}
    "Subprocess commands and their expected stdout for mocking."
    expected_install_names: Union[Sequence[str], Type[Exception]]
    "The expected return result of get_install_names."
    expected_rpaths: Union[Sequence[str], Type[Exception]]
    "The expected return result of get_rpaths."

    def mock_subprocess_run(
        self, cmd: Sequence[str], *args: object, **kwargs: object
    ) -> CompletedProcess:
        """A function to mock subprocess.run with this objects commands."""
        return CompletedProcess(cmd, 0, stdout=self.commands[tuple(cmd)])


@pytest.mark.parametrize(
    "arch_def",
    [
        ToolArchMock(  # Single arch
            commands={
                (
                    "otool",
                    "-L",
                    "example.so",
                ): """\
example.so:
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
""",  # noqa: E501
                (
                    "otool",
                    "-D",
                    "example.so",
                ): """\
example.so:
\texample.so
""",
                (
                    "otool",
                    "-l",
                    "example.so",
                ): """\
example.so:
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
""",
            },
            expected_install_names=(
                "/usr/lib/libc++.1.dylib",
                "/usr/lib/libSystem.B.dylib",
            ),
            expected_rpaths=("path/x86_64",),
        ),
        ToolArchMock(  # Multi arch
            commands={
                (  # Install names match.
                    "otool",
                    "-L",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
example.so (architecture arm64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
""",  # noqa: E501
                (  # Install IDs match.
                    "otool",
                    "-D",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample.so
example.so (architecture arm64):
\texample.so
""",
                (  # Rpaths match.
                    "otool",
                    "-l",
                    "example.so",
                ): """\
example.so (architecture x86_64):
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
example.so (architecture arm64):
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
""",
            },
            expected_install_names=(
                "/usr/lib/libc++.1.dylib",
                "/usr/lib/libSystem.B.dylib",
            ),
            expected_rpaths=("path/x86_64",),
        ),
        ToolArchMock(
            commands={  # Multi arch - not matching install names, rpaths
                (  # Install names do not match (compatibility version).
                    "otool",
                    "-L",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
example.so (architecture arm64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 0.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
""",  # noqa: E501
                (  # Install IDs match.
                    "otool",
                    "-D",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample.so
example.so (architecture arm64):
\texample.so
""",
                (  # Rpaths do not match.
                    "otool",
                    "-l",
                    "example.so",
                ): """\
example.so (architecture x86_64):
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
example.so (architecture arm64):
    cmd LC_RPATH
cmdsize 0
   path path/arm64 (offset 0)
""",
            },
            expected_install_names=NotImplementedError,
            expected_rpaths=NotImplementedError,
        ),
        ToolArchMock(
            commands={  # Multi arch - not matching install IDS
                (  # Install names match.
                    "otool",
                    "-L",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
example.so (architecture arm64):
\texample.so (compatibility version 0.0.0, current version 0.0.0)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 905.6.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1292.100.5)
""",  # noqa: E501
                (  # Different install IDs for different archs.
                    "otool",
                    "-D",
                    "example.so",
                ): """\
example.so (architecture x86_64):
\texample1.so
example.so (architecture arm64):
\texample.so
""",
                (  # RPaths match.
                    "otool",
                    "-l",
                    "example.so",
                ): """\
example.so (architecture x86_64):
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
example.so (architecture arm64):
    cmd LC_RPATH
cmdsize 0
   path path/x86_64 (offset 0)
""",
            },
            expected_install_names=NotImplementedError,
            expected_rpaths=("path/x86_64",),
        ),
    ],
)
def test_names_multi(arch_def: ToolArchMock) -> None:
    with mock.patch("subprocess.run", arch_def.mock_subprocess_run):
        with assert_raises_if_exception(arch_def.expected_install_names):
            assert (
                get_install_names("example.so")
                == arch_def.expected_install_names
            )
        with assert_raises_if_exception(arch_def.expected_rpaths):
            assert get_rpaths("example.so") == arch_def.expected_rpaths

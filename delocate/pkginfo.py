"""Tools for reading and writing PKG-INFO / METADATA without caring about the encoding.

This is based on a copy of the old wheel.pkginfo module.
"""  # noqa: E501

from __future__ import annotations

from email.generator import Generator
from email.message import Message
from email.parser import Parser
from os import PathLike


def read_pkg_info_bytes(bytestr: bytes | str) -> Message:
    """Parse a PKG-INFO or METADATA data string."""
    if isinstance(bytestr, bytes):
        bytestr = bytestr.decode("utf-8")
    return Parser().parsestr(bytestr)


def read_pkg_info(path: bytes | str | PathLike) -> Message:
    """Read a PKG-INFO or METADATA file."""
    with open(path, encoding="utf-8") as headers:
        return Parser().parse(headers)


def write_pkg_info(path: bytes | str | PathLike, message: Message) -> None:
    """Write to a PKG-INFO or METADATA file."""
    with open(path, "w", encoding="utf-8") as out:
        Generator(out, mangle_from_=False, maxheaderlen=0).flatten(message)

"""Tools for reading and writing PKG-INFO / METADATA without caring
about the encoding.

This is based on a copy of the old wheel.pkginfo module.
"""
from email.generator import Generator
from email.message import Message
from email.parser import Parser
from os import PathLike
from typing import Union


def read_pkg_info_bytes(bytestr: Union[bytes, str]) -> Message:
    """Parse a PKG-INFO or METADATA data string."""
    if isinstance(bytestr, bytes):
        bytestr = bytestr.decode("utf-8")
    return Parser().parsestr(bytestr)


def read_pkg_info(path: Union[bytes, str, PathLike]) -> Message:
    """Read a PKG-INFO or METADATA file."""
    with open(path, encoding="utf-8") as headers:
        return Parser().parse(headers)


def write_pkg_info(path: Union[bytes, str, PathLike], message: Message) -> None:
    """Write to a PKG-INFO or METADATA file."""
    with open(path, "w", encoding="utf-8") as out:
        Generator(out, mangle_from_=False, maxheaderlen=0).flatten(message)

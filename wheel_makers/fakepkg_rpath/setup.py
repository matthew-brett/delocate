""" Setup for fakepkg_rpath

This fake package has an extension which links against a library using @rpath
in its install name.  The library will also be signed with an ad-hoc signature.
"""
from os.path import join as pjoin, abspath, dirname
from setuptools import setup, Extension
from subprocess import check_call

HERE = abspath(dirname(__file__))
LIBS = pjoin(HERE, 'libs')
EXTLIB = pjoin(LIBS, 'libextfunc_rpath.dylib')
INSTALL_NAME = '@rpath/libextfunc_rpath.dylib'

arch_flags = ['-arch', 'arm64', '-arch', 'x86_64']  # dual arch
check_call([
    'cc', pjoin(LIBS, 'extfunc.c'),
    '-dynamiclib',
    '-install_name', INSTALL_NAME,
    '-o', EXTLIB,
] + arch_flags)
check_call(['codesign', '--sign', '-', EXTLIB])

exts = [
    Extension(
        'fakepkg.subpkg.module2',
        [pjoin("fakepkg", "subpkg", "module2.c")],
        libraries=['extfunc_rpath'],
        extra_compile_args=arch_flags,
        extra_link_args=['-L' + LIBS, '-rpath', 'libs/'],
        py_limited_api=True
    )
]

setup(
    ext_modules=exts,
    name='fakepkg_rpath',
    version="1.0",
    packages=[
        'fakepkg',
        'fakepkg.subpkg',
        'fakepkg.tests',
        ],
)

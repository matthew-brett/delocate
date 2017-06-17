""" Setup for fakepkg_rpath

This fake package has an extension which links against a library using @rpath
in its install name.  The library will also be signed with an ad-hoc signature.
"""
from os.path import join as pjoin, abspath, dirname
import setuptools # for wheel builds
from distutils.core import setup
from distutils.extension import Extension
from Cython.Build import cythonize
from subprocess import check_call

HERE = abspath(dirname(__file__))
LIBS = pjoin(HERE, 'libs')
EXTLIB = pjoin(LIBS, 'libextfunc_rpath.dylib')
INSTALL_NAME = '@rpath/libextfunc_rpath.dylib'

check_call([
    'cc', pjoin(LIBS, 'extfunc.c'),
    '-dynamiclib',
    '-arch', 'i386', '-arch', 'x86_64', # dual arch
    '-install_name', INSTALL_NAME,
    '-o', EXTLIB,
])
check_call(['codesign', '--sign', '-', EXTLIB])

exts = [
    Extension(
        'fakepkg.subpkg.module2',
        [pjoin("fakepkg", "subpkg", "module2.pyx")],
        libraries=['extfunc_rpath'],
        extra_link_args=['-L' + LIBS, '-rpath', 'libs/'],
    )
]

setup(
    ext_modules = cythonize(exts),
    name='fakepkg_rpath',
    version="1.0",
    packages=[
        'fakepkg',
        'fakepkg.subpkg',
        'fakepkg.tests',
        ],
)

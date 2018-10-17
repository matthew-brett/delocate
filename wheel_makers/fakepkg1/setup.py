""" Setup for fakepkg1

fakepkg1 is a - fake package - that has extensions and links against an external
dynamic lib.  We use it to build a wheel, then test we can delocate it.
"""
from os.path import join as pjoin, abspath, dirname
import setuptools # for wheel builds
from distutils.core import setup
from distutils.extension import Extension
from Cython.Build import cythonize
from subprocess import check_call

HERE = abspath(dirname(__file__))
LIBS = pjoin(HERE, 'libs')
EXTLIB = pjoin(LIBS, 'libextfunc.dylib')

# Compile external extension with absolute path in install id
check_call(['cc', '-dynamiclib', pjoin(LIBS, 'extfunc.c'),
           '-arch', 'i386', '-arch', 'x86_64', # dual arch
            '-o', EXTLIB])
check_call(['install_name_tool', '-id', EXTLIB, EXTLIB])

exts = [Extension('fakepkg1.subpkg.module2',
                  [pjoin("fakepkg1", "subpkg", "module2.pyx")],
                  libraries=['extfunc'],
                  extra_link_args = ['-L' + LIBS]
                 )]

setup(
    ext_modules = cythonize(exts),
    name = 'fakepkg1',
    version = "1.0",
    scripts = [pjoin('scripts', 'fakescript.py')],
    package_data = {'fakepkg1': ['ascript']},
    packages = ['fakepkg1', 'fakepkg1.subpkg', 'fakepkg1.tests'],
)

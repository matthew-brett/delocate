""" Setup for fakepkg1

fakepkg1 is a - fake package - that has extensions and links against an external
dynamic lib.  We use it to build a wheel, then test we can delocate it.
"""
from os.path import join as pjoin, abspath, dirname
from setuptools  import setup, Extension
from Cython.Build import cythonize
from subprocess import check_call

HERE = abspath(dirname(__file__))
LIBS = pjoin(HERE, 'libs')
EXTLIB = pjoin(LIBS, 'libextfunc.dylib')

# Compile external extension with absolute path in install id
arch_flags = ['-arch', 'arm64', '-arch', 'x86_64']  # dual arch
check_call(['cc', '-dynamiclib', pjoin(LIBS, 'extfunc.c'),
            '-o', EXTLIB] + arch_flags)
check_call(['install_name_tool', '-id', EXTLIB, EXTLIB])

exts = [Extension('fakepkg1.subpkg.module2',
                  [pjoin("fakepkg1", "subpkg", "module2.pyx")],
                  libraries=['extfunc'],
                  extra_compile_args=arch_flags,
                  extra_link_args=['-L' + LIBS] + arch_flags,
                  )]

setup(
    ext_modules=cythonize(exts),
    name='fakepkg1',
    version="1.0",
    scripts=[pjoin('scripts', 'fakescript.py')],
    package_data={'fakepkg1': ['ascript']},
    packages=['fakepkg1', 'fakepkg1.subpkg', 'fakepkg1.tests'],
)

#!/usr/bin/env python
""" setup script for delocate package """
import sys
from os.path import join as pjoin
from setuptools import setup, find_packages

# For some commands, use setuptools.
if len(set(('develop', 'bdist_egg', 'bdist_rpm', 'bdist', 'bdist_dumb',
            'install_egg_info', 'egg_info', 'easy_install', 'bdist_wheel',
            'bdist_mpkg')).intersection(sys.argv)) > 0:
    import setuptools

import versioneer

versioneer.VCS = 'git'
versioneer.versionfile_source = pjoin('delocate', '_version.py')
versioneer.versionfile_build = pjoin('delocate', '_version.py')
versioneer.tag_prefix = ''
versioneer.parentdir_prefix = 'delocate-'

setup(name='delocate',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Move OSX dynamic libraries into package',
      author='Matthew Brett',
      maintainer='Matthew Brett',
      author_email='matthew.brett@gmail.com',
      url='http://github.com/matthew-brett/delocate',
      packages=find_packages(),
      install_requires=[
          "machomachomangler; sys_platform == 'win32'",
          "bindepend; sys_platform == 'win32'",
          "wheel",
      ],
      package_data={'delocate.tests':
                    [pjoin('data', '*.dylib'),
                     pjoin('data', '*.txt'),
                     pjoin('data', '*.bin'),
                     pjoin('data', '*.py'),
                     pjoin('data', 'liba.a'),
                     pjoin('data', 'a.o'),
                     pjoin('data', '*.whl'),
                     pjoin('data', 'test-lib'),
                     pjoin('data', '*patch'),
                     pjoin('data', 'make_libs.sh'),
                     pjoin('data', 'icon.ico')]},
      entry_points={
          'console_scripts': [
              'delocate-{} = delocate.cmd.delocate_{}:main'.format(name, name)
              for name in (
                  'addplat',
                  'fuse',
                  'listdeps',
                  'patch',
                  'path',
                  'wheel',
              )
          ]
      },
      license='BSD license',
      classifiers=['Intended Audience :: Developers',
                   "Environment :: Console",
                   'License :: OSI Approved :: BSD License',
                   'Programming Language :: Python',
                   'Operating System :: MacOS :: MacOS X',
                   'Development Status :: 3 - Alpha',
                   'Topic :: Software Development :: Libraries :: '
                   'Python Modules',
                   'Topic :: Software Development :: Build Tools'],
      long_description=open('README.rst', 'rt').read(),
      )

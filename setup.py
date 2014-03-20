#!/usr/bin/env python

from os.path import join as pjoin
from distutils.core import setup

setup(name='delocate',
      version='0.1',
      description='Move dynamic libraries into package',
      author='Matthew Brett',
      maintainer='Matthew Brett',
      author_email='matthew.brett@gmail.com',
      url='http://github.com/matthew-brett/delocate',
      packages=['delocate', 'delocate.tests'],
      package_data = {'delocate.tests':
                      [pjoin('data', '*.dylib'),
                       pjoin('data', 'test-lib'),
                       pjoin('data', 'make_libs.sh')]},
      license='BSD license'
     )

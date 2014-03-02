#!/usr/bin/env python

from distutils.core import setup

setup(name='delocate',
      version='0.1',
      description='Move dynamic libraries into package',
      author='Matthew Brett',
      maintainer='Matthew Brett',
      author_email='matthew.brett@gmail.com',
      url='http://github.com/matthew-brett/delocate',
      packages=['delocate', 'delocate.tests'],
      license='BSD license'
     )

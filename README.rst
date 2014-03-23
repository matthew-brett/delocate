########
Delocate
########

OSX utilities to:

* find dynamic libraries imported from python extensions
* copy needed dynamic libraries to directory within package
* update OSX ``install_names`` and ``rpath`` to cause code to load from copies
  of libraries

Provides scripts:

* ``delocate-listdeps`` -- show libraries a tree depends on
* ``delocate-path`` -- copy libraries a tree depends on into the tree and relink
* ``delocate-wheel`` -- rewrite wheel having copied and relinked library
  dependencies into the wheel tree.

***********
The problem
***********

Let's say you have built a wheel somewhere, but it's linking to dynamic libraries
elsewhere on the machine, so you can't distribute it, because others may not
have these same libraries.  Here's what a scipy wheel looks like. First we unzip
the wheel to get the contents::

    mkdir scipy-wheel-contents
    cd scipy-wheel-contents
    unzip ../scipy-0.14.0b1-cp33-cp33m-macosx_10_6_intel.whl

Then look at the dependencies::

    delocate-listdeps scipy

This gives::

    /System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate
    /usr/lib/libSystem.B.dylib
    /usr/lib/libstdc++.6.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgcc_s.1.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgfortran.3.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libquadmath.0.dylib

So scipy has picked up dynamic libraries from my homebrew installation of
gfortran.

We can fix like this. First make a copy of the wheel so as not to overwrite the
old one::

    cd .. # the directory containing the wheel
    mkdir new_wheel
    cp scipy-0.14.0b1-cp33-cp33m-macosx_10_6_intel.whl new_wheel
    cd new_wheel

Then::

    delocate-wheel scipy-0.14.0b1-cp33-cp33m-macosx_10_6_intel.whl

delocate has made a new directory ``.dylibs`` with copies of the dependencies
that are outside the OSX system trees::

    unzip scipy-0.14.0b1-cp33-cp33m-macosx_10_6_intel.whl
    ls scipy/.dylibs

This gives::

    libgcc_s.1.dylib  libgfortran.3.dylib  libquadmath.0.dylib

Check the links again::

    delocate-listdeps scipy

Result::

    /System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate
    /usr/lib/libSystem.B.dylib
    /usr/lib/libstdc++.6.dylib
    @loader_path/libgcc_s.1.dylib
    @loader_path/libquadmath.0.dylib
    @rpath/libgcc_s.1.dylib
    @rpath/libgfortran.3.dylib
    @rpath/libquadmath.0.dylib

So - system dylibs the same, but the others moved into the wheel tree.

This makes the wheel more likely to work on another machine which does not have
the same version of gfortran installed - in this example.

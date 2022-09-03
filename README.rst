.. image:: https://img.shields.io/pypi/v/delocate
    :target: https://pypi.org/project/delocate/
.. image:: https://travis-ci.org/matthew-brett/delocate.svg?branch=master
    :target: https://travis-ci.org/matthew-brett/delocate
.. image:: https://codecov.io/gh/matthew-brett/delocate/branch/master/graph/badge.svg?token=wvAWRBK5Di
    :target: https://codecov.io/gh/matthew-brett/delocate

########
Delocate
########

macOS utilities to:

* find dynamic libraries imported from python extensions
* copy needed dynamic libraries to directory within package
* update macOS ``install_names`` and ``rpath`` to cause code to load from copies
  of libraries

Provides scripts:

* ``delocate-listdeps`` -- show libraries a tree depends on
* ``delocate-path`` -- copy libraries a tree depends on into the tree and relink
* ``delocate-wheel`` -- rewrite wheel having copied and relinked library
  dependencies into the wheel tree.

`Auditwheel <https://github.com/pypa/auditwheel>`_ is a similar tool for Linux.
Auditwheel started life as a partial fork of Delocate.

***********
The problem
***********

Let's say you have built a wheel somewhere, but it's linking to dynamic
libraries elsewhere on the machine, so you can't distribute it, because others
may not have these same libraries.  Here we analyze the dependencies for
a Scipy wheel::

    $ delocate-listdeps scipy-0.14.0b1-cp34-cp34m-macosx_10_6_intel.whl
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgcc_s.1.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgfortran.3.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libquadmath.0.dylib

By default, this does not include libraries in ``/usr/lib`` and ``/System``.
See those too with::

    $ delocate-listdeps --all scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    /System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate
    /usr/lib/libSystem.B.dylib
    /usr/lib/libstdc++.6.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgcc_s.1.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgfortran.3.dylib
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libquadmath.0.dylib

The output tells me that Scipy has picked up dynamic libraries from my
Homebrew installation of ``gfortran`` (as well as the system libs).

You can get a listing of the files depending on each of the libraries,
using the ``--depending`` flag::

    $ delocate-listdeps --depending scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgcc_s.1.dylib:
        scipy/interpolate/dfitpack.so
        scipy/special/specfun.so
        scipy/interpolate/_fitpack.so
        ...

**********
A solution
**********

We can fix like this::

    $ delocate-wheel -w fixed_wheels -v scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    Fixing: scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    Copied to package .dylibs directory:
        /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgcc_s.1.dylib
        /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgfortran.3.dylib
        /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libquadmath.0.dylib

The ``-w`` flag tells `delocate-wheel` to output to a new wheel directory
instead of overwriting the old wheel.  ``-v`` (verbose) tells you what
`delocate-wheel` is doing.  In this case it has made a new directory in the
wheel zipfile, named ``scipy/.dylibs``. It has copied all the library
dependencies that are outside the macOS system trees into this directory, and
patched the python ``.so`` extensions in the wheel to use these copies instead
of looking in ``/usr/local/Cellar/gfortran/4.8.2/gfortran/lib``.

Check the links again to confirm::

    $ delocate-listdeps --all fixed_wheels/scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    /System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate
    /usr/lib/libSystem.B.dylib
    /usr/lib/libstdc++.6.0.9.dylib
    @loader_path/../../../../.dylibs/libgcc_s.1.dylib
    @loader_path/../../../../.dylibs/libgfortran.3.dylib
    @loader_path/../../../../.dylibs/libquadmath.0.dylib
    @loader_path/../../../.dylibs/libgcc_s.1.dylib
    @loader_path/../../../.dylibs/libgfortran.3.dylib
    @loader_path/../../../.dylibs/libquadmath.0.dylib
    @loader_path/../../.dylibs/libgcc_s.1.dylib
    @loader_path/../../.dylibs/libgfortran.3.dylib
    @loader_path/../../.dylibs/libquadmath.0.dylib
    @loader_path/../.dylibs/libgcc_s.1.dylib
    @loader_path/../.dylibs/libgfortran.3.dylib
    @loader_path/../.dylibs/libquadmath.0.dylib
    @loader_path/libgcc_s.1.dylib
    @loader_path/libquadmath.0.dylib

So - system dylibs the same, but the others moved into the wheel tree.

This makes the wheel more likely to work on another machine which does not have
the same version of Gfortran installed - in this example.

Checking required architectures
===============================

Current Python.org Python and the macOS system Python (``/usr/bin/python``)
are both dual architecture binaries.  For example::

    $ lipo -info /usr/bin/python
    Architectures in the fat file: /usr/bin/python are: x86_64 arm64e

This Big Sur macOS Python has both ``x86_64`` and ``arm64`` (M1) versions
fused into one file.  Earlier versions of macOS had dual architectures that
were 32-bit (``i386``) and 64-bit (``x86_64``).

For full compatibility with system and Python.org Python, wheels built for
Python.org Python or system Python should have the corresponding architectures
— e.g. ``x86_64`` and ``arm64`` versions of the Python extensions and their
libraries.  It is easy to link Python extensions against single architecture
libraries by mistake, and therefore get single architecture extensions and /
or libraries. In fact my Scipy wheel is one such example, because I
inadvertently linked against the Homebrew libraries, which were ``x86_64``
only. To check this you can use the ``--require-archs`` flag::

    $ delocate-wheel --require-archs=intel scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    Traceback (most recent call last):
    File "/Users/mb312/.virtualenvs/delocate/bin/delocate-wheel", line 77, in <module>
        main()
    File "/Users/mb312/.virtualenvs/delocate/bin/delocate-wheel", line 69, in main
        check_verbose=opts.verbose)
    File "/Users/mb312/.virtualenvs/delocate/lib/python2.7/site-packages/delocate/delocating.py", line 477, in delocate_wheel
        "Some missing architectures in wheel")
    delocate.delocating.DelocationError: Some missing architectures in wheel

Notice that this command was using an earlier version of Delocate that
supported Python 2; we now support Python 3 only.

The ``intel`` argument to ``--require-arch`` above requires dual 32- and 64-
bit architecture extensions and libraries. You can see which extensions are at
fault by adding the ``-v`` (verbose) flag::

    $ delocate-wheel -w fixed_wheels --require-archs=intel -v scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    Fixing: scipy-0.14.0-cp34-cp34m-macosx_10_6_intel.whl
    Required arch i386 missing from /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libgfortran.3.dylib
    Required arch i386 missing from /usr/local/Cellar/gfortran/4.8.2/gfortran/lib/libquadmath.0.dylib
    Required arch i386 missing from scipy/fftpack/_fftpack.so
    Required arch i386 missing from scipy/fftpack/convolve.so
    Required arch i386 missing from scipy/integrate/_dop.so
    ...

I need to rebuild this wheel to link with dual-architecture libraries.

Troubleshooting
===============

DelocationError: "library does not exist"
-----------------------------------------

When running ``delocate-wheel`` or its sister command ``delocate-path``, you
may get errors like this::

    delocate.delocating.DelocationError: library "<long temporary path>/wheel/libme.dylib" does not exist

This happens when one of your libraries gives a library dependency with a
relative path.  For example, let's say that some file in my wheel has this for
the output of ``otool -L myext.so``::

    myext.so:
        libme.dylib (compatibility version 10.0.0, current version 10.0.0)
        /usr/lib/libstdc++.6.dylib (compatibility version 7.0.0, current version 60.0.0)
        /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1197.1.1)

The first line means that ``myext.so`` expects to find ``libme.dylib`` at
exactly the path ``./libme.dylib`` - the current working directory from which
you ran the executable.  The output *should* be something like::

    myext.so:
        /path/to/libme.dylib (compatibility version 10.0.0, current version 10.0.0)
        /usr/lib/libstdc++.6.dylib (compatibility version 7.0.0, current version 60.0.0)
        /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1197.1.1)

To set the path to the library, the linker is using the `install name id`_ of
the linked library.  In this bad case, then ``otool -L libme.dylib`` will give
something like::

    libme.dylib (compatibility version 10.0.0, current version 10.0.0)
    /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1197.1.1)

where the first line is the `install name id`_ that the linker picked up when
linking ``myext.so`` to ``libme.dylib``.  Your job is to fix the build process
so that ``libme.dylib`` has install name id ``/path/to/libme.dylib``.
This is not a problem specific to Delocate; you will need to do this to
make sure that ``myext.so`` can load ``libme.dylib`` without ``libme.dylib``
being in the current working directory.  For ``CMAKE`` builds you may want to
check out CMAKE_INSTALL_NAME_DIR_.

****
Code
****

See https://github.com/matthew-brett/delocate

Released under the BSD two-clause license - see the file ``LICENSE`` in the
source distribution.

`travis-ci <https://travis-ci.org/matthew-brett/delocate>`_ kindly tests the
code automatically under Python 3.6 through 3.9.

The latest released version is at https://pypi.python.org/pypi/delocate

*******
Support
*******

Please put up issues on the `Delocate issue tracker
<https://github.com/matthew-brett/delocate/issues>`_.

.. _install name id:
   http://matthew-brett.github.io/docosx/mac_runtime_link.html#the-install-name
.. _CMAKE_INSTALL_NAME_DIR:
   http://www.cmake.org/cmake/help/v3.0/variable/CMAKE_INSTALL_NAME_DIR.html

.. _release-guide:

***********************************
Guide to making a Delocate release
***********************************

A guide for developers who are doing a Delocate release

.. _release-checklist:

Release checklist
=================

* Review the open list of `delocate issues`_.  Check whether there are
  outstanding issues that can be closed, and whether there are any issues that
  should delay the release.  Label them !

* Review and update the release notes.  Review and update the :file:`Changelog`
  file.  Get a partial list of contributors with something like::

      git shortlog -ns 0.6.0..

  where ``0.6.0`` was the last release tag name.

  Then manually go over ``git shortlog 0.6.0..`` to make sure the release notes
  are as complete as possible and that every contributor was recognized.

* Use the opportunity to update the ``.mailmap`` file if there are any
  duplicate authors listed from ``git shortlog -ns``.

* Add any new authors to the ``AUTHORS`` file.  Add any new entries to the
  ``THANKS`` file.

* Check the copyright years in ``doc/conf.py`` and ``LICENSE``

* If you have travis-ci_ building set up you might want to push the code in its
  current state to a branch that will build, e.g::

    git branch -D pre-release-test # in case branch already exists
    git co -b pre-release-test

* Clean::

    git clean -fxd

* Make sure all tests pass on your local machine (from the delocate root
  directory)::

    pytest --pyargs delocate

  Do this on a Python 2 and Python 3 setup.  Check on oldest supported version
  of macOS.  Check on newest supported version.

* Run the same tests after installing into a virtualenv, to test that
  installing works correctly::

    mkvirtualenv delocate-test
    pip install pytest wheel
    git clean -fxd
    pip install -e .
    mkdir for_test
    cd for_test
    pytest --pyargs delocate

* Check the documentation doctests::

    cd doc
    make doctest
    cd ..

* The release should now be ready.

Doing the release
=================

You might want to make tag the release commit on your local machine, push to
pypi_, review, fix, rebase, until all is good.  Then and only then do you push
to upstream on github.

* Make a signed tag for the release with tag of form ``0.6.0``::

    git tag -s 0.6.0

  The package version will be derived from the tag automatically.

* Push the tag with something like ``git push origin 0.6.0`` and that tag will
  be automatically deployed to PyPI.

* Check how everything looks on PyPI - the description, the packages.
  If anything doesn't look right then yank the release and upload with the
  patch version incremented.

* Announce to the mailing lists.  With fear and trembling.

.. _setuptools intro: http://packages.python.org/an_example_pypi_project/setuptools.html
.. _twine: https://pypi.python.org/pypi/twine

.. include:: ../links_names.inc

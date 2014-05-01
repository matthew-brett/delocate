.. _release-guide:

*********************************
Guide to making a delocat release
*********************************

A guide for developers who are doing a delocate release

.. _release-checklist:

Release checklist
=================

* Review the open list of `delocate issues`_.  Check whether there are
  outstanding issues that can be closed, and whether there are any issues that
  should delay the release.  Label them !

* Review and update the release notes.  Review and update the :file:`Changelog`
  file.  Get a partial list of contributors with something like::

      git shortlog -ns 0.2.0..

  where ``0.2.0`` was the last release tag name.

  Then manually go over ``git shortlog 0.2.0..`` to make sure the release notes
  are as complete as possible and that every contributor was recognized.

* Use the opportunity to update the ``.mailmap`` file if there are any duplicate
  authors listed from ``git shortlog -ns``.

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

    nosetests --with-doctest delocate

  Do this on a Python 2 and Python 3 setup.

* Check the documentation doctests::

    cd doc
    make doctest
    cd ..

* The release should now be ready.

Doing the release
=================

The trick here is to get all the testing, pushing to upstream done *before* you
do the final release commit.

You might want to make tag the release commit on your local machine, push to
pypi_, review, fix, rebase, until all is good.  Then and only then do you push
to upstream on github.

* Make an annotated tag for the release with tag of form ``0.3.0``::

    git tag -am 'Second public release' 0.3.0

  Because we're using `versioneer`_ it is the tag which sets the package
  version.

* Once everything looks good, upload the source release to PyPi.  See
  `setuptools intro`_::

    python setup.py register
    python setup.py sdist --formats=gztar,zip bdist_wheel upload

* Remember you'll need your ``~/.pypirc`` file set up right for this to work.
  See `setuptools intro`_.  The file should look something like this::

    [distutils]
    index-servers =
        pypi

    [pypi]
    username:your.pypi.username
    password:your-password

    [server-login]
    username:your.pypi.username
    password:your-password

* Check how everything looks on pypi - the description, the packages.  If
  necessary delete the release and try again if it doesn't look right.

* Push the tag with ``git push origin 0.3``

* Announce to the mailing lists.  With fear and trembling.

.. _setuptools intro: http://packages.python.org/an_example_pypi_project/setuptools.html

.. include:: ../links_names.inc
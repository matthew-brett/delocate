# Contributing

## Contributors guide

This project uses [pre-commit](https://pre-commit.com/) hooks.
You should install these hooks by running the following commands from the project directory:

```sh
pip install pre-commit
pre-commit install
```

Installing IDE plugins supporting [Mypy](https://mypy.readthedocs.io/en/stable/) and [Ruff](https://docs.astral.sh/ruff/) is recommend but not required.
These will be verified by GitHub Actions during a pull request if you are unable to check them locally.

Documentation follows the [Numpydoc Style Guide](https://numpydoc.readthedocs.io/en/latest/format.html).
All public functions must have full documentation.
All private functions must have at least a brief description.

The `wheel_makers` directory holds scripts used to make test data. GitHub Actions will generate this data and upload it as an artifact named `delocate-tests-data`. This can be used to create and commit new test wheels for MacOS even if you don't have access to your own system.

Use [pathlib](https://docs.python.org/3/library/pathlib.html) for any new code using paths.
Refactor any touched functions to use pathlib when it does not break backwards compatibility.
Prefer using `PurePosixPath` to handle relative library paths returned from MacOS tools such as `otool`.

All new functions must have [type hints](https://mypy.readthedocs.io/en/stable/getting_started.html).
All touched functions must be refactored to use type hints, including test functions.

This codebase includes legacy code from the Python 2 era.
Old code should be refactored to use modern standards when touched.

## Maintainers guide

This section is only relevant for maintainers with repo access.

Ensure pre-commit hooks are up-to-date by running `pre-commit autoupdate`.

### Guide to making a Delocate release

A guide for maintainers who are doing a Delocate release.

#### Release checklist

- Review the open list of [issues](http://github.com/matthew-brett/delocate/issues).
  Check whether there are outstanding issues that can be closed, and whether there are any issues that should delay the release.
  Label them!

- Review and update the release notes.
  Review and update the `Changelog` file.
  Get a partial list of contributors with something like::

      git shortlog -ns 0.6.0..

  where `0.6.0` was the last release tag name.

  Then manually go over `git shortlog 0.6.0..` to make sure the release notes
  are as complete as possible and that every contributor was recognized.

- Use the opportunity to update the `.mailmap` file if there are any
  duplicate authors listed from `git shortlog -ns`.

- Add any new authors to the `AUTHORS` file. Add any new entries to the `THANKS` file.

- Check the copyright years in `LICENSE`

- Make sure all tests are passing for the latest commit intended to be released.
  The recommended way to do this is to make a PR for the release.
  Once the PR is merged then the release is now ready.

#### Doing the release

You might want to make tag the release commit on your local machine, push to [PyPI](https://pypi.org/project/delocate), review, fix, rebase, until all is good.
Then and only then do you push to upstream on github.

- Make an annotated tag for the release with tag of form `0.6.0`::

      git tag -a 0.6.0

- Push the tag with something like `git push origin 0.6.0` and that tag will be automatically deployed to PyPI.

- Check how everything looks on PyPI - the description, the packages.
  If anything doesn't look right then yank the release and upload with the patch version incremented.

- Announce to the mailing lists. With fear and trembling.

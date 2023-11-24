# Contributing

This project uses [pre-commit](https://pre-commit.com/) hooks.
You should install these hooks by running the following commands from the project directory:

```sh
pip install pre-commit
pre-commit install
```

Installing IDE plugins supporting [Mypy](https://mypy.readthedocs.io/en/stable/) and [Ruff](https://docs.astral.sh/ruff/) is recommend.

Documentation follows the [Numpydoc Style Guide](https://numpydoc.readthedocs.io/en/latest/format.html).

The `wheel_makers` directory holds scripts used to make test data. GitHub Actions will generate this data and upload it as an artifact named `delocate-tests-data`. This can be used to create and commit new test wheels for MacOS even if you don't have access to your own system.

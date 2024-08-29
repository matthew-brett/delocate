"""Context managers for working with environment variables."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from ..tmpdirs import InTemporaryDirectory


@contextmanager
def TempDirWithoutEnvVars(*env_vars):
    """Remove `env_vars` from the environment and restore them after testing is complete."""  # noqa: E501
    old_vars = {}
    for var in env_vars:
        old_vars[var] = os.environ.get(var, None)
        if old_vars[var] is not None:
            del os.environ[var]
    try:
        with InTemporaryDirectory() as tmpdir:
            yield tmpdir
    finally:
        for var in old_vars:
            if old_vars[var] is not None:
                os.environ[var] = old_vars[var]
            else:
                if var in os.environ:
                    del os.environ[var]


@contextmanager
def _scope_env(**env: str) -> Iterator[None]:
    """Add `env` to the environment and remove them after testing is complete."""  # noqa: E501
    env_save = {key: os.environ.get(key) for key in env}
    try:
        os.environ.update(env)
        yield
    finally:
        for key, value in env_save.items():
            if value is None:
                del os.environ[key]
            else:
                os.environ[key] = value

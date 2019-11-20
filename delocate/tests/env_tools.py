from contextlib import contextmanager
import os

from ..tmpdirs import InTemporaryDirectory


@contextmanager
def TempDirWithoutEnvVars(*env_vars):
    """ Remove `env_vars` from the environment and restore them after
    testing is complete.
    """
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

from contextlib import contextmanager
import os
from typing import Iterator, Text

import six

from ..tmpdirs import InTemporaryDirectory


@contextmanager
def TempDirWithoutEnvVars(*env_vars):
    # type: (*Text) -> Iterator[Text]
    """ Remove `env_vars` from the environment and restore them after
    testing is complete.
    """
    old_vars = {}
    for var in env_vars:
        try:
            old_vars[six.ensure_str(var)] = os.environ[six.ensure_str(var)]
        except KeyError:
            pass
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

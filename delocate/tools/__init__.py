import sys
import os
import zipfile

from os.path import join as pjoin

if sys.platform == 'win32':
    from .win32 import (
        get_install_names,
        get_install_id,
        set_install_name,
        set_install_id,
        get_rpaths,
        add_rpath,
        get_archs,
        lipo_fuse,
        replace_signature,
        validate_signature,
    )
else:
    from .osx import (
        back_tick,
        unique_by_index,
        ensure_writable,
        parse_install_name,
        get_install_names,
        get_install_id,
        set_install_name,
        set_install_id,
        get_rpaths,
        add_rpath,
        zip2dir,
        get_archs,
        lipo_fuse,
        replace_signature,
        validate_signature,
    )

from .common import (
    dir2zip,
    find_package_dirs,
    cmp_contents,
    InstallNameError,
)
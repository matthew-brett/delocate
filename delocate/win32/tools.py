import os

from bindepend import getImports
from machomachomangler.pe import redll


def get_install_names(filename):
    """ Return install names from library named in `filename`

    Returns tuple of install names

    tuple will be empty if no install names, or if this is not an object file.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_names : tuple
        tuple of install names for library `filename`
    """
    return tuple(getImports(filename))


def get_install_id(filename):
    """ Return install id from library named in `filename`

    Returns None if no install id, or if this is not an object file.

    Parameters
    ----------
    filename : str
        filename of library

    Returns
    -------
    install_id : str
        install id of library `filename`, or None if no install id
    """
    # On windows, we don't have the concept of install ID
    return os.path.basename(filename)


def set_install_name(filename, oldname, newname):
    """ Set install name `oldname` to `newname` in library filename

    Parameters
    ----------
    filename : str
        filename of library
    oldname : str
        current install name in library
    newname : str
        replacement name for `oldname`
    """
    # Use machomachomangler
    mapping = {oldname : newname}

    with open(filename, "rb") as f:
        buf = f.read()

    new_buf = redll(buf, mapping)

    with open(filename, "wb") as f:
        f.write(new_buf)

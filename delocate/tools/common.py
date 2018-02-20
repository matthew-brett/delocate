import zipfile
import os

from os.path import join as pjoin

class InstallNameError(RuntimeError):
    pass


def dir2zip(in_dir, zip_fname):
    """ Make a zip file `zip_fname` with contents of directory `in_dir`

    The recorded filenames are relative to `in_dir`, so doing a standard zip
    unpack of the resulting `zip_fname` in an empty directory will result in
    the original directory contents.

    Parameters
    ----------
    in_dir : str
        Directory path containing files to go in the zip archive
    zip_fname : str
        Filename of zip archive to write
    """
    with zipfile.ZipFile(zip_fname, 'w',
                        compression=zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(in_dir):
            for file in files:
                fname = os.path.join(root, file)
                out_fname = os.path.relpath(fname, in_dir)
                z.write(os.path.join(root, file), out_fname)


def find_package_dirs(root_path):
    """ Find python package directories in directory `root_path`

    Parameters
    ----------
    root_path : str
        Directory to search for package subdirectories

    Returns
    -------
    package_sdirs : set
        Set of strings where each is a subdirectory of `root_path`, containing
        an ``__init__.py`` file.  Paths prefixed by `root_path`
    """
    package_sdirs = set()
    for entry in os.listdir(root_path):
        fname = entry if root_path == '.' else pjoin(root_path, entry)
        if os.path.isdir(fname) and os.path.exists(pjoin(fname, '__init__.py')):
            package_sdirs.add(fname)
    return package_sdirs


def cmp_contents(filename1, filename2):
    """ Returns True if contents of the files are the same

    Parameters
    ----------
    filename1 : str
        filename of first file to compare
    filename2 : str
        filename of second file to compare

    Returns
    -------
    tf : bool
        True if binary contents of `filename1` is same as binary contents of
        `filename2`, False otherwise.
    """
    with open(filename1, 'rb') as fobj:
        contents1 = fobj.read()
    with open(filename2, 'rb') as fobj:
        contents2 = fobj.read()
    return contents1 == contents2


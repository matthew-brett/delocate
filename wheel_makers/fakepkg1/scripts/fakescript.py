#!python
"""A fake script."""

import fakepkg1.subpkg.module2  # noqa: F401


def main():
    """Print a message."""
    print("Fake.  Script")


if __name__ == "__main__":
    main()

########
Delocate
########

Utilities to:

* find dynamic libraries imported from python extensions
* copy needed dynamic libraries to directory within package
* update OSX ``install_names`` and ``rpath`` to cause code to load from copies
  of libraries

Here's me rebuilding a scipy wheel to be relocatable::

    # unzip the built wheel to the current directory
    WHEEL_NAME=scipy-0.14.0b1-cp27-none-macosx_10_6_intel.whl
    unzip  ~/dev_trees/scipy/dist/$WHEEL_NAME
    # Run the relocation command
    python -c "import delocate as dl; dl.delocate_path('scipy', 'scipy/.dylibs')"
    # zip up the resulting tree to make a relocatable wheel
    zip -r $WHEEL_NAME scipy scipy*dist-info

# Make wheels and copy into main package
# This is to build the wheels we use for testing
# Need cython and wheel installed to run this script
# Use wheel==0.23 for compatibility with tests.
# Run on earliest supported version of OSX (currently 10.6)
rm */dist/fakepkg*.whl
rm */libs/*.dylib

cd fakepkg1
python setup.py clean bdist_wheel
cd -

cd fakepkg2
python setup.py clean bdist_wheel
cd -

cd fakepkg_rpath
python setup.py clean bdist_wheel
cd -

rm ../delocate/tests/data/fakepkg*.whl
cp */dist/*.whl ../delocate/tests/data
cp */libs/*.dylib ../delocate/tests/data

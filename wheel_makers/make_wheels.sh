# Make wheels and copy into main package
# This is to build the wheels we use for testing
# Need Cython and wheel installed to run this script
# Run on earliest supported version of OSX (currently 10.6)

# Always use Python 2 (for consistent dynamic lib extensions)
py_major=$(python -c 'import sys; print(sys.version_info[0])')
if [ "$py_major" != 2 ]; then
    echo Need Python 2 for wheel building
    exit 1
fi

rm */dist/fakepkg*.whl
rm */libs/*.dylib
rm */MANIFEST

cd fakepkg1
python setup.py clean bdist_wheel
cd -

cd fakepkg2
python setup.py clean bdist_wheel
cd -

cd fakepkg_rpath
python setup.py clean bdist_wheel
cd -

OUT_PATH=../delocate/tests/data
rm $OUT_PATH/fakepkg*.whl
cp */dist/*.whl $OUT_PATH
cp */libs/*.dylib $OUT_PATH
# Record wheel building path
echo $PWD > $OUT_PATH/wheel_build_path.txt

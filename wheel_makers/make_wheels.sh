# Make wheels and copy into main package.
# This is to build the wheels we use for testing.
# Need `wheel` package installed to run this script.
# Python needs to support dual arch builds, and _PYTHON_HOST_PLATFORM
# This appears to require only Python >= 3.3.0

mac_ver=10.9
export MACOSX_DEPLOYMENT_TARGET=${mac_ver}
export _PYTHON_HOST_PLATFORM="macosx-${mac_ver}-universal2"

rm -f */dist/fakepkg*.whl
rm -f */libs/*.dylib
rm -f */MANIFEST

cd fakepkg1
python setup.py clean bdist_wheel --py-limited-api=cp36
cd -

cd fakepkg2
python setup.py clean bdist_wheel
cd -

cd fakepkg_rpath
python setup.py clean bdist_wheel --py-limited-api=cp36
cd -

cd fakepkg_toplevel
python setup.py clean bdist_wheel --py-limited-api=cp36
cd -

cd fakepkg_namespace
python setup.py clean bdist_wheel --py-limited-api=cp36
cd -

OUT_PATH=../delocate/tests/data
rm $OUT_PATH/fakepkg*.whl
cp */dist/*.whl $OUT_PATH
cp */libs/*.dylib $OUT_PATH

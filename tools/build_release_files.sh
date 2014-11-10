# Build sdist and wheels
# Run with `source tools/build_release_files.sh`
workon py27
git clean -fxd
python setup.py sdist --formats=gztar,zip
rm -rf build
python setup.py bdist_wheel
workon py32
rm -rf build
python setup.py bdist_wheel
workon py33
rm -rf build
python setup.py bdist_wheel
workon py34
rm -rf build
python setup.py bdist_wheel
deactivate

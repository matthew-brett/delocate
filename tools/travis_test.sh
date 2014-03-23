echo "python $PYTHON"
which $PYTHON

echo "pip: $PIP"
which $PIP

echo "testing delocate"
export PATH=$PREFIX/bin:$PATH
nosetests-${PY_SHORT_VER} delocate

echo "python $PYTHON"
which $PYTHON

echo "pip $PIP"
which $PIP

echo "testing delocate"
nosetests-${PY_SHORT_VER} delocate

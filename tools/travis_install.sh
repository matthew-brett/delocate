#!/usr/bin/env sh

# Canonical URL for ez_setup
# EZ_SETUP_URL='https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py'
# Cached copy set by mb312 account crontab
EZ_SETUP_URL='https://nipy.bic.berkeley.edu/scipy_installers/buildbot-files/ez_setup.py'

function require_success {
    STATUS=$?
    MESSAGE=$1
    if [ "$STATUS" != "0" ]; then
        echo $MESSAGE
        exit $STATUS
    fi
}


function install_mac_python {
    PY_VERSION=$1
    curl https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-macosx10.6.dmg > python-$PY_VERSION.dmg
    require_success "Failed to download mac python $PY_VERSION"

    hdiutil attach python-$PY_VERSION.dmg -mountpoint /Volumes/Python
    sudo installer -pkg /Volumes/Python/Python.mpkg -target /
    require_success "Failed to install Python.org Python $PY_VERSION"
    M_dot_m=${PY_VERSION:0:3}
    export PYTHON=/usr/local/bin/python$M_dot_m
}

PY_SHORT_VER=${PY_VERSION:0:3}

export PIP_USE_MIRRORS=1

install_mac_python $PY_VERSION

# Install setuptools
curl ${EZ_SETUP_URL} > ez_setup.py
require_success "failed to download setuptools"

sudo $PYTHON ez_setup.py

# Install pip
PREFIX=/Library/Frameworks/Python.framework/Versions/$PY_SHORT_VER
sudo $PREFIX/bin/easy_install-$PY_SHORT_VER pip
export PIP="sudo $PREFIX/bin/pip$PY_SHORT_VER"

# Dependencies for install
$PIP install wheel

# Dependencies for testing
$PIP install nose

# Install package
$PYTHON setup.py install

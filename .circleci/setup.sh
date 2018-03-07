#!/bin/bash
set -eu

WORKSPACE=$(pwd)

# Common definitions from latest bioconda-utils master have to be downloaded before setup.sh is executed.
# This file can be used to set BIOCONDA_UTILS_TAG and MINICONDA_VER.
source .circleci/common.sh

# Set path
echo "export PATH=$WORKSPACE/miniconda/bin:$PATH" >> $BASH_ENV
source $BASH_ENV

if [[ ! -d $WORKSPACE/miniconda ]]; then
    # setup conda and bioconda-utils if not loaded from cache
    mkdir -p $WORKSPACE

    # step 1: download and install miniconda
    if [[ $OSTYPE == darwin* ]]; then
        tag="MacOSX"
    elif [[ $OSTYPE == linux* ]]; then
        tag="Linux"
    else
        echo "Unsupported OS: $OSTYPE"
        exit 1
    fi
    curl -L -o miniconda.sh https://repo.continuum.io/miniconda/Miniconda3-$MINICONDA_VER-$tag-x86_64.sh
    bash miniconda.sh -b -p $WORKSPACE/miniconda

    # step 2: setup channels
    conda config --system --add channels defaults
    conda config --system --add channels conda-forge
    conda config --system --add channels bioconda

    # step 3: install bioconda-utils
    conda install -y --file bioconda_utils/bioconda_utils-requirements.txt

    # step 4: cleanup
    conda clean -y --all

    # Add local channel as highest priority
    conda index $WORKSPACE/miniconda/conda-bld/linux-64 $WORKSPACE/miniconda/conda-bld/osx-64 $WORKSPACE/miniconda/conda-bld/noarch
    conda config --system --add channels file://anaconda/conda-bld

    pip install -r pip-test-requirements.txt
    pip install -r pip-requirements.txt
fi

conda config --get

ls $WORKSPACE/miniconda/conda-bld
ls $WORKSPACE/miniconda/conda-bld/noarch

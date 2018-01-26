#!/bin/bash
#

set -ex

CAFFE2_ROOT="$( cd "$(dirname "$0")"/.. ; pwd -P)"
CONDA_BLD_ARGS=()

# Build for Python 3.6
# Specifically 3.6 because the latest Anaconda version is 3.6, and so it's site
# packages have 3.6 in the name
PYTHON_FULL_VERSION="$(python --version 2>&1)"
if [[ "$PYTHON_FULL_VERSION" == *3.6* ]]; then
  CONDA_BLD_ARGS+=(" --python 3.6")
fi

# Upload to Anaconda.org if needed
if [ -n "$UPLOAD_TO_CONDA" ]; then
  CONDA_BLD_ARGS+=(" --user ${ANACONDA_USERNAME}")
  CONDA_BLD_ARGS+=(" --token ${CAFFE2_ANACONDA_ORG_ACCESS_TOKEN}")
fi

# Reinitialize submodules
git submodule sync
git submodule foreach git fetch
git submodule update --init

# Separate build folder for CUDA builds so that the packages have different
# names
if [[ "${BUILD_ENVIRONMENT}" == *cuda* ]]; then
  conda build "${CAFFE2_ROOT}/conda/cuda" ${CONDA_BLD_ARGS[@]} "$@"
else
  conda build "${CAFFE2_ROOT}/conda/no_cuda" ${CONDA_BLD_ARGS[@]} "$@"
fi

#!/bin/bash
set -e

# Enabling execution time
# Settings -> Advanced Settings Editor -> Notebook -> Insert ``{ "recordTiming": true }``
# under User Preferences (right panel). Using JSON Settings Editor is easier.

# Allow connections temporarily (Ubuntu 20.04, needed to attach debugger)
# echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

echo "================================================"
echo "Starting JupyterLab with ALL SECURITY TURNED OFF"
echo "================================================"
jupyterlab_path_extras="$(pwd)/src/:$(pwd)/jupyterlab/id-translation"
echo "Extending PYTHONPATH: '$jupyterlab_path_extras'"
echo "================================================"

(
  export PYTHONPATH="$PYTHONPATH:$jupyterlab_path_extras"
  cd jupyterlab || exit
  cp jupyter_lab_config.py "$HOME/.jupyter/"
  poetry run jupyter-lab
)

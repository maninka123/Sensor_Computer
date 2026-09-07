#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")"

if [ "$(uname -m)" != "aarch64" ]; then
  echo "ERROR: Use a 64-bit ROCK 5A Linux image (uname -m must be aarch64)." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip libopenblas0
# ROS Noetic's rospy/cv_bridge packages are installed for the system Python.
# Make them visible inside the optimized inference environment as well.
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python - <<'PY'
import platform
import torch
print("Installation OK")
print("Machine:", platform.machine())
print("PyTorch:", torch.__version__)
print("CPU threads:", torch.get_num_threads())
PY

echo "Standalone: .venv/bin/python infer.py sample_input.png --benchmark"
echo "ROS: export NODE_PC_INFERENCE_PYTHON=$PWD/.venv/bin/python"

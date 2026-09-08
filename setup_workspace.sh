#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP=/opt/ros/noetic/setup.bash
SDK_SOURCE="$WS_DIR/.deps/Livox-SDK"
SDK_BUILD="$WS_DIR/.deps/livox-sdk-build"
SDK_INSTALL="$WS_DIR/.deps/livox-sdk-install"
SDK_COMMIT=9306596a2bf15c1343bc023b497465ed0a32909d

if [[ ! -r "$ROS_SETUP" ]]; then
  echo "ERROR: ROS Noetic is not installed at $ROS_SETUP" >&2
  exit 1
fi

mkdir -p "$WS_DIR/.deps"
if [[ ! -d "$SDK_SOURCE/.git" ]]; then
  git clone https://github.com/Livox-SDK/Livox-SDK.git "$SDK_SOURCE"
fi
git -C "$SDK_SOURCE" fetch --quiet origin "$SDK_COMMIT"
git -C "$SDK_SOURCE" checkout --quiet "$SDK_COMMIT"

cmake -S "$SDK_SOURCE" -B "$SDK_BUILD" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$SDK_INSTALL"
cmake --build "$SDK_BUILD" --target install -- -j"$(nproc)"

# shellcheck disable=SC1090
source "$ROS_SETUP"
cd "$WS_DIR"
catkin_make -DCMAKE_BUILD_TYPE=Release -DLIVOX_SDK_ROOT="$SDK_INSTALL" "$@"

echo
echo "Workspace is ready. Start hardware with:"
echo "  cd $WS_DIR && ./run_hardware.sh"

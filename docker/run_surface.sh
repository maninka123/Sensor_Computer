#!/usr/bin/env bash
set -euo pipefail

export ROS_IP="${ROS_IP:-10.20.0.10}"
export ROS_MASTER_URI="${ROS_MASTER_URI:-http://10.20.0.10:11311}"

# The surface owns the ROS Master. This fixed forwarder exposes the sensing
# device's ROSBridge listener as ws://10.20.0.10:9090 in the Docker rig.
socat TCP-LISTEN:9090,reuseaddr,fork TCP:device:9090 &

exec roscore

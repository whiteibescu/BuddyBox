#!/usr/bin/env bash
# Gazebo + Betaflight 데모 월드 실행 (WSL 안에서 실행)
# 사용: bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_gazebo.sh
pkill -f "[g]z sim" 2>/dev/null && sleep 2
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/buddybox-sitl/aeroloop_gazebo/plugins/build
export GZ_SIM_RESOURCE_PATH=/opt/buddybox-sitl/aeroloop_gazebo/models
exec gz sim -r /opt/buddybox-sitl/aeroloop_gazebo/worlds/betaloop_iris_betaflight_demo_harmonic.sdf

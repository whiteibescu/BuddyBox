#!/usr/bin/env bash
# Betaflight SITL 실행 (WSL 안에서 실행, Gazebo를 먼저 띄울 것)
# 사용: bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_sitl.sh
pkill -f "betaflight_[0-9]" 2>/dev/null && sleep 1
cd /opt/buddybox-sitl/betaflight
exec ./obj/betaflight_*_SITL

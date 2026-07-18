#!/usr/bin/env bash
# Gazebo + Betaflight 데모 월드 실행 (WSL 안에서 실행)
# 사용: bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_gazebo.sh
pkill -f "[g]z sim" 2>/dev/null && sleep 2
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/buddybox-sitl/aeroloop_gazebo/plugins/build
export GZ_SIM_RESOURCE_PATH=/opt/buddybox-sitl/aeroloop_gazebo/models
export QT_QPA_PLATFORM=xcb
if [ "$1" = "gpu" ]; then
  echo "[start_gazebo] GPU 렌더링 모드 (빠름 — 창이 안 뜨면 인자 없이 재실행)"
else
  # WSLg에서 GPU 렌더링이 실패해 창이 안 뜨는 경우 대비 (느리지만 확실)
  echo "[start_gazebo] 소프트웨어 렌더링 모드 (확실하지만 느림 — 'gpu' 인자로 가속 시도 가능)"
  export LIBGL_ALWAYS_SOFTWARE=1
fi
exec gz sim -r -v 3 /opt/buddybox-sitl/aeroloop_gazebo/worlds/betaloop_iris_betaflight_demo_harmonic.sdf

#!/usr/bin/env bash
# Gazebo + Betaflight 데모 월드 실행 (WSL 안에서 실행)
# 사용: bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_gazebo.sh [gpu] [light|meteor]
#   gpu    : 하드웨어 가속 시도 (창이 안 뜨면 빼고 재실행)
#   meteor : Meteor75 whoop 모델 월드 (75mm 1S, 단순 도형 비주얼이라 light만큼 가벼움)
#   light : 경량 월드 — 배경/그림자 제거 + 드론 비주얼을 단순 도형으로 교체 (물리·플러그인은 동일)
#           WSLg에서 dae 메시 렌더링이 병목이라 개발 시에는 light 권장
pkill -f "[g]z sim" 2>/dev/null && sleep 2
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/buddybox-sitl/aeroloop_gazebo/plugins/build
export GZ_SIM_RESOURCE_PATH=/opt/buddybox-sitl/aeroloop_gazebo/models
export QT_QPA_PLATFORM=xcb
WORLD=betaloop_iris_betaflight_demo_harmonic.sdf
USE_GPU=0
for arg in "$@"; do
  case "$arg" in
    gpu)    USE_GPU=1 ;;
    light)  WORLD=betaloop_iris_betaflight_demo_harmonic_light.sdf ;;
    meteor) WORLD=betaloop_meteor75_betaflight_demo_harmonic.sdf ;;
  esac
done
if [ "$USE_GPU" = "1" ]; then
  echo "[start_gazebo] GPU 렌더링 모드 (빠름 — 창이 안 뜨면 인자 없이 재실행)"
else
  # WSLg에서 GPU 렌더링이 실패해 창이 안 뜨는 경우 대비 (느리지만 확실)
  echo "[start_gazebo] 소프트웨어 렌더링 모드 (확실하지만 느림 — 'gpu' 인자로 가속 시도 가능)"
  export LIBGL_ALWAYS_SOFTWARE=1
fi
echo "[start_gazebo] 월드: $WORLD"
exec gz sim -r -v 3 "/opt/buddybox-sitl/aeroloop_gazebo/worlds/$WORLD"

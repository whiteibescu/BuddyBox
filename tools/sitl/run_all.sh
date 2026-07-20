#!/usr/bin/env bash
# Gazebo + Betaflight SITL + 가상 비행 한 방 실행 (WSL 안에서 실행)
#
# 사용:
#   bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/run_all.sh          # 소프트웨어 렌더링 (확실)
#   bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/run_all.sh gpu      # GPU 렌더링 (빠름)
#   bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/run_all.sh meteor   # Meteor75 whoop 모델 (gpu와 조합 가능)
#
# 끝난 뒤 Gazebo/SITL은 백그라운드에 남는다 (비행만 다시 하려면 virtual_flight.py 재실행).
# 전부 종료: bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/stop_all.sh
set -e
REPO=/mnt/c/VisionWorkspace/BuddyBox

WORLD=betaloop_iris_betaflight_demo_harmonic.sdf
USE_GPU=0
for arg in "$@"; do
  case "$arg" in
    gpu)    USE_GPU=1 ;;
    meteor) WORLD=betaloop_meteor75_betaflight_demo_harmonic.sdf ;;
  esac
done

echo "[1/3] 기존 인스턴스 정리..."
pkill -f "[g]z sim" 2>/dev/null || true
pkill -f "betaflight_[0-9]" 2>/dev/null || true
sleep 2

echo "[2/3] Gazebo 시작 (로그: /tmp/gz.log)..."
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/buddybox-sitl/aeroloop_gazebo/plugins/build
export GZ_SIM_RESOURCE_PATH=/opt/buddybox-sitl/aeroloop_gazebo/models
export QT_QPA_PLATFORM=xcb
if [ "$USE_GPU" = "1" ]; then
  echo "        GPU 렌더링 모드 (창이 안 뜨면 인자 없이 재실행)"
else
  echo "        소프트웨어 렌더링 모드 (느리지만 확실 — 'gpu' 인자로 가속 시도 가능)"
  export LIBGL_ALWAYS_SOFTWARE=1
fi
echo "        월드: $WORLD"
nohup gz sim -r "/opt/buddybox-sitl/aeroloop_gazebo/worlds/$WORLD" \
  > /tmp/gz.log 2>&1 &
sleep 15
if grep -q "failed to bind" /tmp/gz.log; then
  echo "!! 플러그인 포트 충돌 — stop_all.sh 실행 후 다시 시도하세요"; exit 1
fi

echo "[3/3] Betaflight SITL 시작 (로그: /tmp/sitl.log)..."
cd /opt/buddybox-sitl/betaflight
nohup ./obj/betaflight_*_SITL > /tmp/sitl.log 2>&1 &
sleep 5

echo ""
echo "=== 가상 비행 시작 — Gazebo 창을 보세요! ==="
cd "$REPO/python/examples"
SITL_HOST=127.0.0.1 python3 virtual_flight.py

echo ""
echo "Gazebo/SITL은 계속 떠 있습니다."
echo "  비행 재실행 : cd $REPO/python/examples && SITL_HOST=127.0.0.1 python3 virtual_flight.py"
echo "  전부 종료   : bash $REPO/tools/sitl/stop_all.sh"

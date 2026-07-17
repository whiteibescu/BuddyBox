#!/usr/bin/env bash
# BuddyBox SITL 환경 구축 (WSL2 Ubuntu 24.04 전용, root로 실행)
#
#   - Gazebo Harmonic (공식 OSRF 저장소)
#   - Betaflight SITL 빌드 (obj/main/betaflight_SITL.elf)
#   - aeroloop_gazebo 브리지 플러그인 빌드 (libBetaflightPlugin.so)
#
# 실행: wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/setup_wsl.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== [1/4] 기본 패키지 ==="
apt-get update -q
apt-get install -y -q curl lsb-release gnupg git build-essential cmake rapidjson-dev python3 pkg-config

echo "=== [2/4] Gazebo Harmonic ==="
curl -sSL https://packages.osrfoundation.org/gazebo.gpg -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
  > /etc/apt/sources.list.d/gazebo-stable.list
apt-get update -q
apt-get install -y -q gz-harmonic libgz-sim8-dev

SRC=/opt/buddybox-sitl
mkdir -p "$SRC"

echo "=== [3/4] Betaflight SITL 빌드 ==="
if [ ! -d "$SRC/betaflight" ]; then
  git clone --depth 1 https://github.com/betaflight/betaflight.git "$SRC/betaflight"
fi
cd "$SRC/betaflight"
make TARGET=SITL -j"$(nproc)"

echo "=== [4/4] aeroloop_gazebo 플러그인 빌드 ==="
if [ ! -d "$SRC/aeroloop_gazebo" ]; then
  git clone -b gz --depth 1 https://github.com/betaflight/aeroloop_gazebo.git "$SRC/aeroloop_gazebo"
fi
# gz 브랜치는 최상위가 아니라 plugins/ 아래에 CMakeLists가 있고 전용 스크립트로 빌드한다
bash "$SRC/aeroloop_gazebo/build_plugin.sh"

echo "=== 완료 ==="
ls -la "$SRC/betaflight/obj/" | grep -i sitl || true
find "$SRC/aeroloop_gazebo/plugins/build" -name '*.so' || true

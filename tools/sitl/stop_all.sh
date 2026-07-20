#!/usr/bin/env bash
# Gazebo + Betaflight SITL 전부 종료
pkill -f "[g]z sim" 2>/dev/null || true
pkill -f "betaflight_[0-9]" 2>/dev/null || true
sleep 1
pgrep -af "[g]z sim|betaflight_[0-9]" || echo "모두 종료됨"

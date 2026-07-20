"""가상 첫 비행: ARM → 스로틀 상승 → 호버 → 하강 → DISARM.

전제 (WSL 터미널 2개):
    bash tools/sitl/start_gazebo.sh     # 터미널 1: Gazebo 창 뜸
    bash tools/sitl/start_sitl.sh      # 터미널 2: Betaflight SITL

실행 (Windows PowerShell):
    $env:SITL_HOST = (wsl hostname -I).Trim().Split()[0]
    python virtual_flight.py

주의: SITL 최초 1회는 ARM 스위치 설정 필요 (docs/sitl-gazebo.md 참고):
    CLI> aux 0 0 0 1700 2100
    CLI> set small_angle = 180
    CLI> save
"""

import os
import socket
import struct
import sys
import time

sys.path.insert(0, "..")
from buddybox import CH_THROTTLE
from buddybox.sitl import BuddyBoxSitl

HOST = os.environ.get("SITL_HOST", "127.0.0.1")
AUX1 = 4  # CH5 = ARM 스위치


def msp_status(host):
    """MSP_STATUS(101)를 읽어 모드 플래그를 반환. bit0 = ARMED."""
    s = socket.create_connection((host, 5761), timeout=3)
    payload = struct.pack("<BB", 0, 101)
    ck = 0
    for b in payload:
        ck ^= b
    s.sendall(b"$M<" + payload + bytes([ck]))
    hdr = b""
    while len(hdr) < 5:
        hdr += s.recv(5 - len(hdr))
    data = b""
    while len(data) < hdr[3] + 1:
        data += s.recv(hdr[3] + 1 - len(data))
    s.close()
    return struct.unpack("<I", data[6:10])[0]


def main():
    with BuddyBoxSitl(host=HOST) as bb:
        print(f"SITL: {bb.port}")
        print("1) 중립 + 스로틀 최소")
        bb.neutral()
        time.sleep(2)

        print("2) ARM (AUX1=1900)")
        bb.set_channel_us(AUX1, 1900)
        time.sleep(1.5)
        flags = msp_status(HOST)
        print(f"   ARMED = {'YES' if flags & 1 else 'NO'} (flags={flags:#x})")
        if not flags & 1:
            print("   ARM 실패 — SITL CLI에서 aux 설정했는지 확인 (docstring 참고)")
            return

        print("3) 스로틀 상승 -- Gazebo 창을 보세요!")
        for thr in range(1100, 1700, 25):
            bb.set_channel_us(CH_THROTTLE, thr)
            time.sleep(0.15)
        print("   호버 (5초)")
        time.sleep(5)

        print("4) 하강")
        for thr in range(1700, 1000, -20):
            bb.set_channel_us(CH_THROTTLE, thr)
            time.sleep(0.12)

        print("5) DISARM")
        bb.set_channel_us(CH_THROTTLE, 988)
        bb.set_channel_us(AUX1, 1000)
        time.sleep(1)
        print(f"   ARMED = {'YES' if msp_status(HOST) & 1 else 'NO'}")


if __name__ == "__main__":
    main()

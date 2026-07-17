# Betaflight SITL + Gazebo 시뮬레이션 (sim-to-real)

하드웨어 없이 **진짜 Betaflight 펌웨어**(SITL 빌드)를 Gazebo 물리 시뮬레이터와 연결해
제어 로직을 개발·검증한다. sim-to-real gap을 줄이는 핵심은 **제어 코드가 시뮬과
실물에서 100% 동일**하다는 것:

```
[실물]  제어로직 → SafetyLimiter → BuddyBox(시리얼)   → PPM → TX15 → ELRS → 실제 FC
[시뮬]  제어로직 → SafetyLimiter → BuddyBoxSitl(UDP)  → Betaflight SITL ↔ Gazebo
         └──────────── 동일한 코드 (한 줄만 교체) ────────────┘
```

채널 의미(AETR, 988~2012µs)와 전송 주기(50Hz)도 실물 경로와 동일하게 맞춰져 있다.

## 통신 구조 (UDP, 127.0.0.1)

| 포트 | 방향 | 내용 |
|---|---|---|
| 9002 | SITL → Gazebo | 모터 출력 |
| 9003 | Gazebo → SITL | 센서/자세 데이터 (FDM) |
| **9004** | **우리 코드 → SITL** | **RC 입력** (`double timestamp + 16×uint16 µs`, 40바이트) |
| 5761 | Configurator ↔ SITL | MSP over TCP (설정용) |

`BuddyBoxSitl`(python/buddybox/sitl.py)이 9004 송신을 담당한다.

## 환경 구축 (최초 1회)

전제: Windows 11 + WSL2, Ubuntu 24.04 배포판 설치됨.

```powershell
wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/setup_wsl.sh
```

스크립트([tools/sitl/setup_wsl.sh](../tools/sitl/setup_wsl.sh))가 하는 일:
1. Gazebo Harmonic 설치 (OSRF 공식 저장소)
2. Betaflight 소스 클론 + `make TARGET=SITL` → `betaflight_SITL.elf`
3. [aeroloop_gazebo](https://github.com/betaflight/aeroloop_gazebo) (gz 브랜치) 플러그인 빌드

설치 위치: WSL 내부 `/opt/buddybox-sitl/`

## 실행 순서

터미널 3개 (모두 `wsl -d Ubuntu-24.04`):

```bash
# ① Gazebo (WSLg로 GUI 표시됨)
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/buddybox-sitl/aeroloop_gazebo/build
gz sim -r /opt/buddybox-sitl/aeroloop_gazebo/worlds/<월드파일>.sdf

# ② Betaflight SITL
cd /opt/buddybox-sitl/betaflight && ./obj/main/betaflight_SITL.elf
```

```powershell
# ③ Windows에서 우리 제어 루프 (WSL localhost는 Windows에서 접근 가능)
cd python\examples
python autonomous_loop.py sitl
```

Betaflight Configurator 연결(설정 변경 시): `tcp://127.0.0.1:5761`

## 검증 체크리스트

- [ ] SITL 부팅 후 Configurator Receiver 탭에서 `autonomous_loop.py sitl` 채널 반응 확인
- [ ] SITL에서 ARM 조건 설정(AUX 채널) 후 가상 이륙
- [ ] 실물과 동일한 SafetyLimiter 한계로 비행 특성 확인

## sim-to-real 주의점

- Gazebo 기체 모델의 질량·추력이 실기와 다르면 PID 감각이 달라짐 — 모델 파라미터 튜닝은 별도 작업
- SITL은 센서 노이즈가 이상적 — 실기 전 반드시 props-off 검증 재수행
- WSL2의 localhost 포워딩으로 Windows↔WSL UDP는 기본 동작하지만, 문제 시 `.wslconfig`에 `networkingMode=mirrored` 설정

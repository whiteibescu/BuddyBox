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
2. Betaflight 소스 클론 + `make TARGET=SITL` → `obj/betaflight_<버전>_SITL`
3. [aeroloop_gazebo](https://github.com/betaflight/aeroloop_gazebo) (gz 브랜치) 플러그인 빌드
   (`build_plugin.sh` 사용 → `plugins/build/libBetaflightPlugin.so`)

설치 위치: WSL 내부 `/opt/buddybox-sitl/`

## 실행 순서 (검증된 명령어)

WSL 터미널 2개 + Windows PowerShell 1개:

```bash
# ① WSL 터미널 1 — Gazebo (WSLg로 Windows에 창 뜸)
wsl -d Ubuntu-24.04
bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_gazebo.sh

# ② WSL 터미널 2 — Betaflight SITL
wsl -d Ubuntu-24.04
bash /mnt/c/VisionWorkspace/BuddyBox/tools/sitl/start_sitl.sh
```

```powershell
# ③ Windows PowerShell — 가상 비행 (ARM→상승→호버→하강→DISARM)
cd c:\VisionWorkspace\BuddyBox\python\examples
$env:SITL_HOST = (wsl hostname -I).Trim().Split()[0]
python virtual_flight.py

# 또는 자동 제어 루프
$env:BUDDYBOX_SITL_HOST = $env:SITL_HOST
python autonomous_loop.py sitl
```

### SITL 최초 1회 설정 (ARM 스위치)

새 eeprom.bin일 때 한 번만. Betaflight Configurator를 `tcp://<WSL IP>:5761`로
연결하거나, CLI로:

```
aux 0 0 0 1700 2100     # ARM = AUX1(CH5) 1700~2100
set small_angle = 180
save                     # SITL이 종료됨 → start_sitl.sh로 재시작
```

가상 비행 검증 결과 (2026-07-18): ARM → 스로틀 상승 → 호버 → DISARM 시퀀스가
MSP_STATUS ARMED 플래그 기준으로 정상 동작 확인.

## 검증 체크리스트

- [ ] SITL 부팅 후 Configurator Receiver 탭에서 `autonomous_loop.py sitl` 채널 반응 확인
- [ ] SITL에서 ARM 조건 설정(AUX 채널) 후 가상 이륙
- [ ] 실물과 동일한 SafetyLimiter 한계로 비행 특성 확인

## 검증 결과 (2026-07-18)

Windows(BuddyBoxSitl) → WSL(Betaflight SITL) RC 경로 **end-to-end 검증 완료**:
송신 AETR [1756, 1244, 988, 2012] → MSP_RC 판독값과 완전 일치 (PASS).

**주의 — WSL2 UDP localhost**: NAT 모드에선 Windows→WSL로 UDP가 127.0.0.1로
포워딩되지 않는다 (TCP는 됨). 반드시 WSL IP로 송신할 것:

```powershell
$env:BUDDYBOX_SITL_HOST = (wsl hostname -I).Trim().Split()[0]
python autonomous_loop.py sitl
```

(또는 `.wslconfig`에 `networkingMode=mirrored` 설정 시 localhost 사용 가능)

## sim-to-real 주의점

- Gazebo 기체 모델의 질량·추력이 실기와 다르면 PID 감각이 달라짐 — 모델 파라미터 튜닝은 별도 작업
- SITL은 센서 노이즈가 이상적 — 실기 전 반드시 props-off 검증 재수행
- WSL2의 localhost 포워딩으로 Windows↔WSL UDP는 기본 동작하지만, 문제 시 `.wslconfig`에 `networkingMode=mirrored` 설정

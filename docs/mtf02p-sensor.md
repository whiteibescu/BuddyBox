# MTF-02P 하방 센서 (옵티컬 플로우 + 레인지파인더) — Meteor75 Pro 2

MicoAir **MTF-02P**(옵티컬 플로우 + ToF 거리)를 Meteor75 Pro 2의 FC(BETAFPV Matrix G4 3IN1,
타깃 `BETAFPVG473`)에 연결하고, Betaflight가 센서 값을 읽도록 설정한 기록이다.
목적은 **Betaflight를 이너 루프로 유지한 채 센서 값을 MSP로 PC에 가져오는 것**이며,
고도·위치 제어 로직은 BuddyBox(PC) 쪽에서 직접 작성한다.

```
MTF-02P ──UART2(MSP, 115200)──▶ Betaflight FC ──MSP──▶ PC (BuddyBox)
                                 (rangefinder/opticalflow 처리)
```

> **진행 상황 (2026-10-11)**: 납땜·센서 설정·Betaflight 2026.6.2 인식 완료.
> Sensors 탭 Sonar 그래프(거리)와 Debug 그래프(플로우) 수신 확인.
> 남은 일: 기체 하단 장착 + 플로우 방향 보정, PC 쪽 MSP 판독 코드.

## 1. 배선

![MTF-02P ↔ Matrix G4 배선](img/mtf02p-wiring.png)

센서 커넥터(SH1.0-4P) 실크 순서는 **G-V-R-T**, 동봉 케이블 색은 **검정-빨강-노랑-초록**이다.
TX/RX는 교차 연결한다.

| 선 색 | 센서 핀 | FC 패드 |
|---|---|---|
| 검정 | G (GND) | **G** |
| 빨강 | V (5V) | **5V** |
| 노랑 | R (센서 RX) | **T2** |
| 초록 | T (센서 TX) | **R2** |

![FC 납땜 완료](img/mtf02p-fc-soldered.jpg)

![MTF-02P](img/mtf02p-sensor.jpg)

- 저가 케이블은 색 배열이 뒤집혀 오는 경우가 있으니, 납땜 전 센서 GND 패드와 검정선 도통을 확인한다.
- TX/RX를 바꿔 꽂아도 손상은 없다(데이터만 안 들어옴). **5V/GND 역결선은 센서 손상 위험.**
- 플럭스는 인두를 담그지 말고 패드·선에 직접 바른다. 작업 후 IPA로 잔여물 제거(R2/T2 신호 패드 주변).
- 센서 파란 LED = 전원 정상. LED만으로는 데이터선 연결 여부를 알 수 없다.

## 2. 센서 출력 프로토콜을 MSP로 변경 (MicoAssistant)

MicoAir 센서는 출고 시 자체 프로토콜(MicoLink)로 출력하므로 **MSP로 바꿔야** Betaflight가 해석한다.
센서를 떼지 않고 FC를 USB-UART 브리지로 써서 설정한다.

1. 배터리 연결(USB만으로는 5V 패드에 전원이 안 들어갈 수 있음)
2. Betaflight CLI:
   ```
   serialpassthrough UART2 115200
   ```
   `Forwarding, power cycle to exit.`가 나와야 성공.
   **이 버전은 포트를 번호가 아닌 이름으로 받는다** — `serialpassthrough 1 115200`은 `Invalid port`.
3. Betaflight App(브라우저)을 **완전히 종료** — 포트를 잡고 있으면 `Failed to open serial port`
4. [MicoAssistant](https://micoair.com/assistant/) (Windows, .NET Framework 4.7.2 필요) → 같은 COM 포트, 115200 접속
5. Data 메뉴에서 거리값 변화 확인 → Params에서 **Protocol = MSP** 저장
6. 배터리·USB 모두 분리 후 재연결 → passthrough 해제 (설정을 저장하는 명령이 아니라서 복구할 것 없음)

> 실전 이슈: MicoAssistant Log에 `###ERROR IN input: UNKNOWN COMMAND, TRY 'HELP'###`(hex)가
> 반복되면 passthrough가 걸리지 않은 상태다. MicoAssistant의 식별 요청에 Betaflight CLI가 대답하고 있는 것.

`serialpassthrough`는 FC가 USB↔UART2 바이트를 해석 없이 그대로 넘기게 하는 임시 모드다.
지상 설정·디버깅용이며 비행 중에는 쓸 수 없다(FC가 센서를 읽지 않음).

## 3. Betaflight 펌웨어 — 2026.6.2 필요

**2025.12.x에서는 MTF 센서가 인식되지 않는다.** 빌드 옵션에서 Range Finder / Optical Flow를 켜도
MicoAir용 드라이버(`USE_RANGEFINDER_MT`, `USE_OPTICALFLOW_MT`)가 자동 포함되지 않기 때문이다.

| 증상 (2025.12.5) | 원인 |
|---|---|
| `rangefinder_hardware`에 `MTF02P`가 목록에 보이고 설정도 저장됨 | 이름 목록은 드라이버 포함 여부와 무관하게 표시 |
| `tasks`에 RANGEFINDER/OPTICALFLOW 없음, Sonar 토글 비활성 | 감지 함수가 컴파일되지 않아 센서 미감지 |

- 소스 비교: [common_post.h @ 2025.12.5](https://github.com/betaflight/betaflight/blob/2025.12.5/src/main/target/common_post.h) vs
  [@ 2026.6.2](https://github.com/betaflight/betaflight/blob/2026.6.2/src/main/target/common_post.h)
- 동일 증상 이슈: [betaflight-configurator #5058](https://github.com/betaflight/betaflight-configurator/issues/5058)
- 2025.12.x를 꼭 써야 하면 Expert Mode → Custom Defines에 `USE_RANGEFINDER_MT USE_OPTICALFLOW_MT`

### 빌드 설정 (Firmware Flasher)

| 항목 | 값 |
|---|---|
| Board | `BETAFPVG473` |
| Version | **2026.6.2** (정식) |
| Radio Protocol | CRSF (내장 ELRS) |
| OSD Protocol | Digital (Walksnail, MSP DisplayPort) |
| Motor Protocol | DSHOT |
| Other Options | LED Strip, VTX, **Range Finder, Optical Flow**, Position Hold(선택) |

- Firmware Flasher 탭은 FC **연결 해제 상태**에서만 보인다.
- `Initiating reboot to bootloader`에서 멈추면: 브라우저 사이트 권한에 `DFU in FS Mode`가 있으면
  FC는 이미 DFU 진입 상태 → **페이지 새로고침 후 다시 Flash**. 권한 ✕는 누르지 말 것.
- 플래싱하면 설정이 공장 기본값으로 초기화된다(ARM 스위치 `aux`, `align_board_yaw = -90`, PID 등 소실).
  반드시 백업 → 복구한다. Betaflight App이 플래싱 직전 `BTFL_cli_backup_*.txt`를 자동 저장한다.
- 복구 전 `The accelerometer is enabled but it is not calibrated` 경고는 정상(복구 파일에 `acc_calibration` 포함).

## 4. 설정

복구 파일: [configs/betaflight/meteor75_2026.6.2_restore.txt](../configs/betaflight/meteor75_2026.6.2_restore.txt)
(원본 백업: [meteor75_2025.12.5-alpha_backup.txt](../configs/betaflight/meteor75_2025.12.5-alpha_backup.txt))

CLI에 파일 전체를 붙여 넣으면 `save`까지 실행된다. 원본 대비 추가된 내용:

```
serial UART2 1 115200 57600 0 115200   # UART2 기능 0(미사용) → 1(MSP)
feature RANGEFINDER
feature OPTICALFLOW
set rangefinder_hardware = MTF02P
set opticalflow_hardware = MT
set debug_mode = OPTICALFLOW
batch end
```

**`feature RANGEFINDER/OPTICALFLOW`가 없으면** 하드웨어를 지정해도 작업(task)이 시작되지 않는다
([tasks.c](https://github.com/betaflight/betaflight/blob/2026.6.2/src/main/fc/tasks.c) — 센서 감지 + feature 둘 다 필요).

`serial` 기능값은 비트 합: 1 = MSP, 64 = Serial RX, 131072 = MSP DisplayPort.

| UART | 기능값 | 용도 |
|---|---|---|
| UART2 | 1 | MTF-02P (MSP) |
| UART3 | 64 | 내장 ELRS (CRSF) — 보드 기본값이라 diff에 안 나옴 |
| UART4 | 131073 | Walksnail HD VTX (MSP + DisplayPort) |

## 5. 동작 확인

1. 배터리 연결 상태에서 CLI `tasks` → **RANGEFINDER, OPTICALFLOW** 작업이 목록에 있어야 함
2. Sensors 탭 → **Sonar** 토글 활성화 → 센서 앞에서 손을 움직이면 거리 그래프 변화
3. **Debug** 토글 → 무늬 있는 바닥 위 10cm 이상에서 기체를 움직이면 플로우 값 변화

- **Sonar** = 레인지파인더(바닥까지 거리). 최초 지원 센서가 초음파(HC-SR04)라 이름만 남은 것.
  그래프 값은 `MSP_SONAR_ALTITUDE`로 받은 **기울기 보정 고도(cm)**. 범위 밖·과도한 기울기는 음수.
- 옵티컬 플로우는 Configurator에 전용 그래프가 없다(Live Sensor Data: Gyro/Accel/Mag/Altitude/Sonar/Pitot/Debug뿐 —
  [LiveSensorPanel.vue](https://github.com/betaflight/betaflight-configurator/blob/master/src/components/tabs/sensors/LiveSensorPanel.vue)).
  `debug_mode = OPTICALFLOW`로 Debug 그래프에서 본다.
- Debug 채널은 한 모드만 선택 가능. 레인지파인더 원시값을 보려면 `debug_mode = RANGEFINDER`(debug[1] 원시, debug[2] 보정).

### OPTICALFLOW 디버그 채널 (단위 0.001 rad/s)

| 채널 | 내용 |
|---|---|
| debug[0], [1] | 회전 보정된 플로우 X, Y |
| debug[2], [3] | 자이로 보상값 (기체 회전 성분) |
| debug[4], [5] | 회전 성분 제거 플로우 X, Y (무효 시 0) |
| debug[6], [7] | 필터링된 최종 플로우 X, Y |

- 플로우는 **거리 80mm 이상 + 최신 거리값**일 때만 유효 처리된다
  ([rangefinder_lidarmt.c](https://github.com/betaflight/betaflight/blob/master/src/main/drivers/rangefinder/rangefinder_lidarmt.c)).
- 조도 60 lux 이상, 단색이 아닌 무늬 있는 바닥이 필요하다.

## 6. 장착과 방향 (예정)

- 렌즈 면이 **바닥과 평행하게 정면으로** 향하도록, 가능하면 기체 중앙(무게중심 근처)에 장착
- 다리(랜딩기어)가 시야각 42° 원뿔 안에 들어오지 않게 한다. 덕트 장착형이 유리
  - [Meteor75 Pro Landing Gears](https://makerworld.com/models/1339408-meteor75-pro-landing-gears) (약 12mm, PLA/TPU)
  - [Meteor 75 Pro Landing Gear TPU](https://makerworld.com/en/models/1373764-betafpv-meteor-75-pro-landing-gear-tpu) (10mm, 약 4.1g)
  - 둘 다 "Meteor75 Pro" 기준 — Pro 2 덕트 호환은 확인 필요
- 센서 뒷면 금속 접점은 테이프로 절연
- 앞뒤 방향은 아무렇게나 붙여도 설정으로 보정 가능 ([#15711](https://github.com/betaflight/betaflight/issues/15711) 방법):
  1. 기체를 **앞으로 밀 때 debug[7]이 증가**해야 함 → 아니면 `opticalflow_rotation` 90/180/270
  2. 좌우로 밀 때 debug[6] 부호가 반대면 `opticalflow_flip_x = ON`
  3. MicoAssistant의 Flow Direction은 **NONE 유지** (양쪽에서 돌리면 이중 회전)

## 7. PC에서 값 읽기 (BuddyBox)

| 데이터 | MSP 명령 | 페이로드 |
|---|---|---|
| 거리(고도) | `MSP_SONAR_ALTITUDE` (58) | int32, cm, 기울기 보정. 음수 = 범위 밖/측정 실패 |
| 플로우 | `MSP_DEBUG` (254) | int16 × 8 (`debug_mode = OPTICALFLOW`일 때 위 표) |

- 제어 입력으로는 debug[4]/[5] 또는 [6]/[7] (회전 성분 제거된 실제 이동 흐름)
- 2026.6의 `MSP2_CLI_SETTING`(0x3010, 2026.6.2 `msp_protocol_v2_betaflight.h` 기준)으로 PC에서 CLI 설정값을 직접 읽고 쓸 수 있다.
- **벤치**: USB 연결로 바로 판독 가능 → 판독 코드 작성 완료 (아래)

### 구현 (python/)

| 모듈 | 역할 |
|---|---|
| `buddybox/msp.py` | `MspSerial`(USB-VCP) · `MspClient`(SITL TCP) 공용 API — `sonar_altitude_m()`, `debug()`, `attitude()`, `altitude()`. `open_msp("COM7" / "sitl")` |
| `buddybox/follow/sensors.py` | `SensorPoller`: 백그라운드 폴링(기본 20 Hz) → `RangeFlowSample(alt_m, flow_x/y rad/s, vx/vy m/s)`. 속도 = 플로우 × 고도 |
| `buddybox/follow/hover.py` | `HoverHold`: 고도 PID(목표 m → 스로틀 Δ) + 위치 유지(속도 Kv + 드리프트 적분 Kp → roll/pitch) |
| `tools/mtf02p_monitor.py` | 벤치 모니터. `python tools/mtf02p_monitor.py COM7 --check` 로 장착 방향 확인 |

```
python tools/mtf02p_monitor.py COM7 --hz 20 --raw        # 거리·플로우 실시간
python examples/person_follow.py --port COM5 --msp COM7  # Pro Micro + FC USB (벤치, 프롭 제거)
```

`--msp COMx`를 주면 ARM 확인(MSP_STATUS)과 센서 폴링이 같은 포트를 공유한다.
설정 `alt_hold`·`pos_hold`를 켜면 HOVER/LOST/FOLLOW에서 센서 홀드가 동작하고, 센서가 없거나
무효(범위 밖·0.4 s 이상 지연)이면 자동으로 기존 개루프 트림으로 돌아간다 — [person-follow.md](person-follow.md#하방-센서-홀드-mtf-02p) 참고.
### 비행 중 다운링크 — OSD 판독 (채택)

현재 체인(PC → Pro Micro PPM → TX15 → ELRS)은 업링크만 있다. **비행 중 값은 이미 PC가 받고 있는
Walksnail 영상의 OSD 글자를 읽어서 얻는다** — 추가 하드웨어·조종기 개조 없음, 지연 = 영상 지연(수십 ms).

Betaflight 2026.6.2 OSD 에 센서 전용 요소가 있다 ([osd_elements.c](https://github.com/betaflight/betaflight/blob/2026.6.2/src/main/osd/osd_elements.c)):

| 요소 | CLI | 표시 | 내용 |
|---|---|---|---|
| `OSD_LIDAR_DIST` | `osd_lidar_dist_pos` | `RF:%3d` | `rangefinderGetLatestAltitude()` cm (MSP 58 과 동일 값), 무효 = `RF:---` |
| `OSD_DEBUG2` | `osd_debug2_pos` | `D2 %5d %5d %5d %5d` | debug[4..7] — OPTICALFLOW 모드에서 회전 제거 X,Y · 필터링 X,Y |
| `OSD_DEBUG` | `osd_debug_pos` | `DBG %5d ×4` | debug[0..3] (필요 시) |

```
# python tools/osd_calibrate.py --pos  가 출력하는 값. 셀 (col,row), 프로파일 1
set osd_lidar_dist_pos = 2625     # RF  (1, 18)
set osd_debug2_pos = 2634         # D2  (10, 18)
set debug_mode = OPTICALFLOW
save
```

위치값 인코딩([osd.h](https://github.com/betaflight/betaflight/blob/2026.6.2/src/main/osd/osd.h)):
x 하위 5비트 + HD X 비트(bit 10, x ≥ 32), y << 5, 프로파일 플래그 bit 11~13, 타입 bit 14~15.
HD 캔버스는 53 × 20 셀. 기존 `osd_vbat_pos = 2563` = (3, 16) 프로파일 1 로 검증.

PC 쪽 (`python/`):

| 모듈 | 역할 |
|---|---|
| `buddybox/vision/osd.py` | 흰 글자+검은 외곽선 마스크 → 셀 분할 → 글리프 템플릿 상관 분류 → `RF:`/`D2` 파싱. `osd_pos()` 인코더 |
| `buddybox/follow/sensors.py` `OsdSensorSource` | 프레임마다 판독해 `RangeFlowSample` 생성 (SensorPoller 와 같은 `latest()`) → `HoverHold` 그대로 사용 |
| `tools/osd_calibrate.py` | **벤치**: FC USB MSP 실측값을 정답으로 글리프 템플릿 학습 → `osd_glyphs.json` (격자 보정 포함). 폰트 팩 무관 |
| `tools/osd_sensor.py` | **비행**: 카메라/녹화 영상에서 실시간 판독·CSV. `person_follow.py --osd-glyphs osd_glyphs.json` 으로 UI 에도 연결 |

절차:
1. CLI 에 위 설정 → 고글/VRX 화면 아래쪽에 `RF: 85` 와 `D2 ...` 가 보여야 한다.
2. 벤치(배터리 + FC USB + VRX 캡처): `python tools/osd_calibrate.py --camera "UVC Camera" --msp COM7 --show`
   센서 앞에서 손을 움직이고 기체를 밀어 숫자가 고루 바뀌게 60초 → 자가 검증 % 확인.
3. 수동 비행: `python tools/osd_sensor.py --camera "UVC Camera" --glyphs osd_glyphs.json --csv flight.csv`
   또는 `person_follow.py --osd-glyphs osd_glyphs.json` (상태 줄에 alt / v 표시, 세션 frames.jsonl 에 기록).
   녹화해 두면 `--video session/raw.mp4` 로 사후 추출도 된다.

제약: 값 해상도 cm · 정수 / 갱신율 = OSD 갱신(DisplayPort, 10~20 Hz 수준) / 글자 위에 다른 OSD 요소가
겹치면 안 됨 / 캡처 해상도를 바꾸면 격자 재학습. 흰 벽·하늘 배경은 외곽선 조건으로 걸러진다.

**2026-10-11 실측 (VRX Pro 캡처, 1080p)**: 캡처 영상에 Betaflight OSD 가 그대로 들어온다. `RF:` 는 책상 위 `1` → 들면 `23`
→ 범위 밖 `---`, `D2` 는 정지 시 `0 -5 4 -6`(≈0), 센서 앞에서 손을 움직이면 수천 — **거리·광류 모두 PC 까지 도달 확인**.
- 격자는 1920/53 = 36.2 px 등분이 맞다(회귀 추정 35.97 px). 글자가 셀 안에서 2~8 px 밀리므로 판독기는 셀 상자가 아니라
  **글자 경계상자**로 정규화한다.
- **맨 아래 두 행(18·19)은 Walksnail 자체 상태 표시**(`3.9V`, `25.0Mbps`, `Standby Mode…`)와 겹친다 — 윗부분이 셀 하단
  9 px 를 침범해 판독을 망쳤고, 셀의 아래 18 % 를 버려서 해결. 가능하면 요소를 그보다 위 행에 두고
  `osd_calibrate.py --pos --rf-pos col,row --d2-pos col,row` 로 CLI 값을 받는다. 판독기/뷰어도 같은 옵션으로 위치를 받는다
  (글리프 JSON 에 저장됨).
- 손으로 라벨한 4 프레임만 학습해도 121 프레임 중 75 개를 정확히 읽었다 (`tools/osd_glyphs_walksnail_1080p.json`,
  Walksnail 기본 폰트 1080p 부트스트랩). 벤치 MSP 학습을 거치면 더 올라간다.

### 대안 (보류) — ELRS MSP-over-CRSF 중계

조종기 Lua 가 `crossfireTelemetryPush(0x7A, {0xC8, 0xEA, status, size, cmd, …})` 로 MSP 요청을 보내고
`crossfireTelemetryPop()` 으로 `0x7B` 응답을 받는 경로(Betaflight Lua 스크립트와 동일,
[msp_shared.c](https://github.com/betaflight/betaflight/blob/master/src/main/telemetry/msp_shared.c):
status 바이트 = seq 4비트 | start bit4 | version bit5~6 | error bit7, 청크 ≤ 57 B, XOR 체크섬).
PC 로 넘기려면 조종기 시리얼 포트를 **LUA 모드**로 써야 하는데, EdgeTX 소스상 USB-VCP 에 LUA 모드가
막혀 있지는 않지만 TX15 에서 동작 확인이 없고([EdgeTX #6569](https://github.com/EdgeTX/edgetx/issues/6569):
TX15 AUX UART 매핑 오류·Lua 시리얼 실패 보고), 왕복 지연·대역폭도 OSD 경로보다 나쁘다. 진짜 MSP 가
필요해질 때(설정 쓰기 등) 다시 본다.

| 경로 | 판정 |
|---|---|
| **Walksnail OSD 판독** | 채택 — 하드웨어 추가 없음, 지연 최소, 정밀도 cm/정수 |
| ELRS 텔레메트리 + MSP 요청 → TX15 Lua → USB | 보류 — 프로토콜은 확인, 조종기 시리얼 LUA 모드 미검증 |
| ESP32-C3 등 별도 무선 | 보류 — 75 mm 1S 무게·전력 부담 |

- 어느 경로든 왕복 지연이 있으므로 **빠른 안정화는 FC, PC는 목표·상위 판단·로깅**으로 분리한다.

## 8. 참고: 2026.6 업그레이드에서 바뀐 점 (이 기체 기준)

- 비행: Airmode LPF 제거, D-term 기본값 조정(`d_max_advance` 0), `thrust_linear` 곡선 재계산, 필터 Biquad→SVF.
  큰 재튜닝은 불필요하지만 첫 비행은 짧은 호버링으로 확인.
- 시리얼 CRSF·HD OSD 동작 변화 없음. CRSF 텔레메트리에 AHRS·기압 고도·수직 속도 추가.
- 백업의 `set` 항목 이름은 2026.6.2 소스에 전부 존재(복구 에러 없음 확인).
- Betaflight 자체 위치 유지(칼만 필터 위치 추정, [PR #15584](https://github.com/betaflight/betaflight/pull/15584))는
  master(2026.12 예정)에 병합 — 2026.6.2에는 미포함. BuddyBox는 자체 제어를 쓰므로 무관.

출처: [Betaflight 2026.6 Release Notes](https://betaflight.com/docs/wiki/release/Betaflight-2026-6-Release-Notes)

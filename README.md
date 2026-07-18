# BuddyBox

PC에서 RadioMaster **TX15 Max**의 트레이너(Student/Teacher) 기능을 이용해
ELRS → Betaflight 드론을 관제하는 프로젝트.

```
Python (PC) ──USB 시리얼──▶ Pro Micro ──PPM──▶ TX15 Max DSC 포트
                                                  │ EdgeTX Trainer (Master/Jack)
                                                  ▼
                                        내장 ELRS ──▶ 수신기 ──▶ Betaflight FC
```

PC는 스틱 4채널(Roll/Pitch/Yaw/Throttle)만 제어하고, **ARM·모드 스위치는 조종기에 유지**한다.

## 안전 계층

1. **트레이너 스위치(모멘터리)** — 놓는 순간 조종기 스틱으로 복귀
2. **Pro Micro 타임아웃** — 시리얼 프레임 500ms 단절 시 PPM 정지 → EdgeTX가 스틱 복귀
3. **Betaflight 페일세이프** — ELRS 링크 상실 시 Drop/GPS Rescue

## 구성

| 경로 | 내용 |
|---|---|
| [firmware/promicro_ppm/](firmware/promicro_ppm/) | Pro Micro 펌웨어 (시리얼 → PPM) |
| [firmware/clock_check/](firmware/clock_check/) | 보드 클럭(16/8MHz) 판별 스케치 |
| [python/buddybox/](python/buddybox/) | PC 제어 라이브러리 |
| [python/examples/](python/examples/) | 수동 조종 GUI, 채널 스윕 테스트 |
| [docs/wiring.md](docs/wiring.md) | Pro Micro ↔ DSC 포트 배선 |
| [docs/radio-setup.md](docs/radio-setup.md) | EdgeTX 트레이너 설정 + 안전 체크리스트 |

## 배선 다이어그램

![Pro Micro 배선](docs/img/promicro-wiring.svg)

| 핀 | 뜻 | 이 프로젝트에서 |
|---|---|---|
| **10** | 디지털 입출력 | **PPM 신호 출력 → 플러그 TIP(L)** |
| **GND** (3개) | 접지 (전부 내부 연결) | **아무거나 → 플러그 SLEEVE(⏚)** |
| TX0 / RX1 | 하드웨어 시리얼 | 미사용 (PC 통신은 USB로) |
| 2~9, 14~16 | 디지털 입출력 | 미사용 |
| A0~A3 | 아날로그 입력 | 미사용 |
| RAW / VCC / RST | 외부 전원 입력 / 5V 출력 / 리셋 | 미사용 — **GND와 헷갈리지 말 것!** |

## 시작하기

1. **배선** — [docs/wiring.md](docs/wiring.md) 대로 D10→Tip, GND→Sleeve 연결
2. **펌웨어** — Arduino IDE에서 보드 클럭 확인 후 `promicro_ppm.ino` 업로드
3. **조종기** — [docs/radio-setup.md](docs/radio-setup.md) 대로 Trainer Master/Jack 설정
4. **PC**
   ```
   cd python
   pip install -r requirements.txt
   cd examples
   python channel_sweep.py        # 조종기 Trainer 화면에서 신호 확인
   python manual_control.py       # 슬라이더/키보드 수동 조종
   ```
5. **검증** — 프롭 제거 후 Betaflight Receiver 탭 → 페일세이프 3종 테스트 (체크리스트 참조)

## 시리얼 프로토콜 (PC → Pro Micro, 115200 baud)

19바이트 고정 프레임, 50Hz:

| 바이트 | 내용 |
|---|---|
| 0–1 | 헤더 `0xA5 0x5A` |
| 2–17 | 8채널 × uint16 LE, 펄스폭 µs (988–2012) |
| 18 | 2–17 바이트 XOR 체크섬 |

채널 순서(AETR): CH1 Roll, CH2 Pitch, CH3 Throttle, CH4 Yaw, CH5–8 예비(중립).

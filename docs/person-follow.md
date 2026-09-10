# 사람 추적 + 호버링 유지 (Meteor75 Pro 2 · Walksnail VRX Pro)

Walksnail VRX Pro의 UVC 출력(= 웹캠처럼 잡힘)을 PC에서 받아 RF-DETR로 사람을 검출하고,
사람이 화면 중앙·일정 크기로 유지되도록 스틱 4채널을 BuddyBox 트레이너 체인으로 보낸다.

```
VRX Pro (UVC 1080p30) ─▶ UvcSource ─▶ DetectWorker(RF-DETR ONNX, 별도 스레드) ─▶ TargetTracker
                                                                                  │ Track(cx, cy, h)
                            FlightSupervisor(STANDBY/HOVER/FOLLOW) ◀──────────────┘
                                    │ StickCommand
                            SafetyLimiter ─▶ BuddyBox / BuddyBoxSitl / sim
                                    │
                            Session(raw.mp4 + frames.jsonl + events.jsonl)  ← 비행마다 자동 기록
```

관련 파일:

| 경로 | 역할 |
|---|---|
| `python/buddybox/vision/capture.py` | UVC/파일 소스 (`UvcSource`, `FileSource`, 프리셋, 장치 이름 탐색) |
| `python/buddybox/vision/detector.py` | RF-DETR ONNX (`OnnxDetector`) + OpenCV HOG 대체 (`HogDetector`) |
| `python/buddybox/vision/tracker.py` | 타깃 선택·유지·LOST 판정 (`TargetTracker`) |
| `python/buddybox/follow/controller.py` | 화면 오차 → 스틱 PID, 호버 트림 학습 (`FollowController`, `FollowConfig`) |
| `python/buddybox/follow/state.py` | 모드/상태 감독, LOST 하강 (`FlightSupervisor`) |
| `python/buddybox/follow/pipeline.py` | 캡처→검출→추적→제어→송신 스레드, 세션 기록 연동 |
| `python/buddybox/follow/session.py` | 세션 기록 포맷 (`Session`, `load_session`) |
| `python/examples/person_follow.py` | tkinter UI 앱 |
| `python/examples/person_follow.json` | 튜닝 값 (UI "설정 저장"으로 갱신) |
| `python/tools/session_report.py` | 세션 요약 리포트 + 프레임 격자 + 그래프 + CSV |
| `python/tools/session_replay.py` | 기록된 검출로 다른 PID 설정을 오프라인 재실행 (개루프 비교) |
| `tools/person_follow.bat` | Windows 실행 메뉴 (바탕화면 `BuddyBox Person Follow.lnk`) |

## Walksnail VRX Pro 캡처 노하우 (중요)

- VRX Pro UVC 포맷은 **MJPG 1280x720@60** 과 **MJPG 1920x1080@30** 두 개뿐이다. 다른 해상도를 요청하면
  화면에 "please select 1080p mode" 안내가 뜬다. → 프리셋 `vrx1080` / `vrx720` 만 사용.
- Windows **MSMF 백엔드는 1080p 요청을 720p로 떨어뜨린다.** 반드시 **DSHOW** 백엔드 (`--cap-backend dshow`, 기본값).
- 장치명은 **"UVC Camera"** 로 잡힌다. USB 재연결 시 인덱스가 바뀌므로 인덱스가 아니라 **이름으로 지정**한다
  (`--camera "UVC Camera"`, 이름 일부 매칭). 이름 조회는 `pygrabber` 필요.
- 이 PC의 Python 3.12 환경은 onnxruntime **CPU 전용**(`--provider cpu`), OpenCV 5.0.
  RF-DETR nano(384x384)는 CPU에서 약 55ms → 검출 스레드가 분리되어 있어 제어 루프(30Hz)는 영향받지 않는다.
- **UI 창이 배경으로 가면 추론이 10배(500ms) 느려지는 현상**이 있었다. onnxruntime이 논리 코어 32개 전부에
  스핀 스레드를 띄우는데 배경 창 프로세스는 선점당하기 때문. 스레드를 코어 절반(16)으로 제한하면 배경에서도 60ms.
  기본값이 `cpu_count // 2` 이고 `--threads N` 또는 `BUDDYBOX_ORT_THREADS` 로 바꿀 수 있다
  (측정: 32→500ms, 16→60ms, 8→130ms, 4→95ms; 프로세스 우선순위 HIGH 는 오히려 악화).
- 원본 구현: `d:\VisionWorkspace\unity-prototypes\Vision_POC\rf-detr\src\realtime_uvc.py`, `run_walksnail.bat`.
  캡처·검출·녹화 코드는 거기서 포팅했다.

## 설치

```powershell
cd python
pip install -r requirements-vision.txt
```

모델은 레포에 포함하지 않는다. 다음 중 하나:

1. `python/models/rfdetr_nano_coco.onnx` + `rfdetr_nano_coco.classes.json` 복사 (gitignore 됨)
2. 환경변수 `BUDDYBOX_MODEL=<onnx 경로>` (classes.json 은 같은 폴더에 있어야 함)
3. 기본 탐색 경로: `D:\VisionWorkspace\unity-prototypes\Vision_POC\rf-detr\models\exported\rfdetr_nano_coco.onnx`
4. 모델 없이 시험: `--detector hog` (OpenCV 기본 보행자 검출기, 정확도 낮음)

## 실행

```powershell
tools\person_follow.bat            # 메뉴: VRX+sim / VRX+ProMicro / VRX+SITL / 웹캠 / 파일 / 장치목록
```

바탕화면의 **`BuddyBox Person Follow.lnk`** 가 이 배치 파일의 바로가기다 (기존 `Walksnail Detect.lnk` 와 같은 방식).
다른 PC에서 다시 만들려면 PowerShell:

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:USERPROFILE\Desktop\BuddyBox Person Follow.lnk")
$s.TargetPath = "D:\Workspace\BuddyBox\tools\person_follow.bat"; $s.WorkingDirectory = "D:\Workspace\BuddyBox\tools"
$s.IconLocation = "C:\Windows\System32\imageres.dll,177"; $s.Save()
```

또는 직접:

```powershell
cd python\examples
python person_follow.py --list                                  # UVC 장치 확인
python person_follow.py                                          # VRX 1080p30 + sim 백엔드
python person_follow.py --port auto                              # 실물 Pro Micro (자동 탐지)
python person_follow.py --port sitl --sitl-host <WSL IP>         # Betaflight SITL
python person_follow.py --camera "HD Webcam" --preset webcam720  # 웹캠으로 개발
python person_follow.py --camera rec.mp4 --preset raw            # 녹화 파일 재생으로 개발
```

## UI

- **연결**: 카메라(이름 콤보, 프리셋), 백엔드(`sim` / `sitl` / `auto` / COMx).
- **ARM / DISARM**: AUX1(CH5)을 1900/1000µs로 보낸다. `ARM` 은 실수 방지를 위해 **STANDBY 에서 3초 안에 두 번** 눌러야
  실제로 나간다(첫 클릭은 "ARM? 한 번 더"). `DISARM` 은 즉시 스로틀 최소 + STANDBY 로도 만든다.
  - **결과 표시**: SITL 백엔드는 Betaflight MSP(TCP 5761)로 실제 ARMED 플래그를 읽어 초록 `ARMED` / 회색 `DISARMED` /
    빨강 `ARM FAILED` 로 표시하고, 실패 시 막은 이유(THROTTLE, ARMSWITCH, ANGLE 등)를 아래 줄에 보여준다.
    실물 Pro Micro 백엔드는 되돌아오는 텔레메트리가 없어 `ARM SENT · 확인 불가` 로만 표시한다(명령은 나갔지만 기체가
    실제로 ARM 됐는지는 조종기·기체 LED·모터로 확인). 오버레이 우상단에도 같은 상태가 색으로 표시된다.
- **모드**: `1 STANDBY`(스틱 중립·스로틀 최소) → `2 HOVER`(호버 트림 유지) → `3 FOLLOW`(사람 추적).
  `긴급 정지 · DISARM`(Space/Esc) 은 스로틀 최소 + STANDBY + AUX1 DISARM 을 한 번에 한다. 상태 줄에 현재
  스로틀·트림·학습 오프셋·µs·하강량이 표시된다.
- **트림/고도 탭**: 호버 스로틀, 보정 폭, 목표 위치/크기, 트림 학습 속도, LOST 하강, 스로틀 슬루, 스로틀 모드,
  고도 기준점(head/center), 좌우 축, 토글(거리 유지·고도 보조·트림 학습·반전), `학습값 → 트림 반영`, `학습 초기화`.
- **PID 탭**: 좌우/거리/고도 Kp·Ki·Kd, 데드존, 축 상한, LOST 판정 시간. 전부 실시간 반영.
- **도구 탭**: 세션 기록 시작/중지(R), 자동 기록 방식(항상/모드 전환 시/끔), 스냅샷(P), 세션 폴더 열기, 설정 저장/불러오기,
  마지막 세션 리포트 생성(`session_report.py --sheet --plot` 실행 후 폴더 열림).
- **영상 클릭** = 그 사람으로 타깃 변경, **우클릭** = 타깃 해제(가장 큰 사람 자동 재선택), `W/S` = 호버 스로틀 ±0.01.

화면 오버레이: 회색 박스=검출된 사람 전부, 초록 박스=타깃, 노랑=LOST(직전 위치 유지 중), 자홍 원=고도 기준점(머리),
하늘색 점선·십자·사각형=목표 세로 위치와 데드존, 오른쪽 세로 브래킷=목표 박스 높이, 좌하단 두 사각형=스틱 위치.

## 제어 로직

정규화 오차 (모두 -1~+1):

| 오차 | 정의 | 제어 축 | 의미 |
|---|---|---|---|
| `x` | `(cx - 0.5) * 2` | yaw (또는 roll) | 사람이 오른쪽 → 오른쪽으로 회전 |
| `size` | `(target_height - h) / target_height` | pitch | 박스가 작음(멀다) → 전진 |
| `y` | `(target_y - ref_y) * 2`, `ref_y` = 머리 위치(`head`) 또는 박스 중심(`center`) | throttle 보정 | 기준점이 위쪽 → 기체가 낮다 → 스로틀 ↑ |

- 각 축 PID → 데드존 → 축별 상한 (`max_lateral`, `max_pitch`, `max_throttle_delta`).
- 스로틀 = `hover_throttle + 학습 오프셋 + PID 보정`. 고도 센서가 없으므로 사람 대비 상대 고도만 유지한다.
- 고도 기준점은 기본 **머리(박스 상단)** 다. 박스 중심은 가까이 있는 사람의 다리가 화면 아래에서 잘리면 위로 끌려
  올라가 "기체가 낮다"고 오판하게 만든다. 머리 위치는 잘림에 영향받지 않는다.
- 부호가 반대로 반응하면 `좌우/피치/스로틀 반전` 토글.
- 모든 출력은 `SafetyLimiter`(기울기·스로틀 상한·슬루레이트)를 거친다. 스로틀은 별도 슬루(`max_throttle_rate_per_s`, 기본 0.6/s)
  라서 STANDBY→HOVER 전환 시 최소→트림까지 1초 남짓 걸린다.

상태 전이:

| 상황 | 출력 |
|---|---|
| STANDBY | 중립 + 스로틀 최소 (offset 모드: 오프셋 0) |
| HOVER | 중립 + 호버 트림(학습 오프셋 포함) |
| FOLLOW + 타깃 유효 | PID 출력 |
| FOLLOW 중 타깃 없음/LOST, 또는 영상 끊김 | 중립 + 호버 트림, `lost_descend_after_s` 뒤부터 `lost_descend_rate`/s 로 서서히 하강 (최대 `lost_descend_max`) |

LOST 는 `lost_after_s`(기본 0.6초) 동안 재검출이 없을 때, 영상 끊김은 `video_timeout_s`(1초) 프레임 없음일 때.
LOST 이후 2.5초가 지나면 타깃을 버리고 가장 큰 사람을 자동 재선택한다. 타깃이 다시 잡히면 하강량은 0으로 돌아간다.

## 호버 스로틀 — 개루프의 한계와 대책

증상: HOVER/FOLLOW 에서 기체가 계속 상승하거나(트림 높음), 반대로 아예 못 뜬다(트림 낮음).

**핵심: 고도 센서가 없으면 고정 스로틀로는 진짜 호버가 안 된다.** `hover_throttle` 이 실제 호버점보다 조금이라도 높으면
계속 상승하고, 조금 낮으면 계속 가라앉는다. 중간의 "딱 뜨는 값"은 배터리 전압·기온·기체 무게에 따라 매 순간 바뀌므로
한 값으로 고정할 수 없다. 그래서 아래 대책(트림 학습, 그리고 특히 offset 모드/ALT_HOLD)이 필요하다.

`hover_throttle` ↔ 스로틀 환산: `-0.35≈32%`, `-0.25≈37%`, `-0.15≈42%`, `-0.05≈47%`, `0.0=50%`.
1S 75mm 훕의 호버는 대략 **37~43%(-0.25 ~ -0.13)** 이다. 기본값은 **-0.25(≈37%)** 로 두었고 (너무 높으면 날아가고
너무 낮으면 못 뜨므로 중간에서 시작), 실기에서 W/S 로 미세 조정한다.

원인별 대책:

1. **HOVER 는 개루프다.** 예전 기본 -0.2(40%)는 살짝 높아 상승, -0.35(32%)는 낮아 못 뜸 → 중간 -0.25 로 조정.
   조금 낮은 트림(천천히 가라앉음)이 높은 트림(날아감)보다 안전하다.
2. **FOLLOW 의 보정 폭(±0.12)이 트림 오차보다 작으면** 못 잡는다. 게다가 상승하다 사람이 화면 아래로 빠지면
   LOST → "잘못된 트림"으로 복귀 → 더 상승하는 악순환. 이제 추적 중에 **트림을 학습**하고(`trim_learning`,
   `trim_learn_rate` 0.15/s, 위로 +0.10 / 아래로 -0.30 한계), LOST 때도 학습된 트림으로 호버하며, LOST 가 3초 넘으면
   서서히 하강한다.
3. **박스 중심 기준의 고도 오차**는 가까운 사람의 다리가 잘릴 때 위로 튄다 → 머리 기준으로 바꿨다 (`altitude_reference`).
4. 스로틀 Ki 는 0으로 두고(학습이 적분 역할), Kd 0.08 로 상승률 감쇠를 넣었다.

트림 맞추는 절차 (실기):

1. 조종기로 직접 호버시키고 스로틀 스틱 위치를 눈으로 기억한다 (30%면 -0.40, 35%면 -0.30, 40%면 -0.20).
2. UI 를 HOVER 로 두고 `호버 스로틀` 을 그 값보다 **0.05 낮게** 놓는다.
3. **SH 를 1~2초만 당겼다 놓는다.** 가라앉으면 W 로 0.01~0.02 올리고, 뜨면 S 로 내린다. 반복해서 3~5초 유지되는 값을 찾는다.
4. 배터리가 빠지면 같은 스로틀에서 가라앉으므로 비행 중 학습 오프셋이 +로 자란다. 착륙 후 `학습값 → 트림 반영` 을 누르고
   `설정 저장` 하면 다음 비행의 시작값이 된다. 새 배터리는 다시 낮은 값에서 시작.

SITL(Gazebo) + 웹캠으로 시험할 때의 주의: 웹캠은 기체에 달려 있지 않아서 **고도 피드백이 없다.** 고도 보조와 트림 학습이
켜져 있으면 사람 위치에 따라 스로틀이 한쪽으로 밀려 학습 한계까지 상승/하강한다. SITL 에서는 `고도 보조` 를 끄고
yaw/pitch 부호와 게인만 확인하거나, 켜더라도 학습 오프셋이 한계(+0.10)에서 멈추는지만 본다.
Gazebo `betaloop_meteor75` 모델의 호버는 약 41%(-0.18) 이다.

### 대안: 조종기가 고도를 잡고 PC 는 보정만 (offset 모드)

EdgeTX SYS→Trainer 에서 **Thr 채널만 `+=`(Add) 30~50%** 로 두고 (Ail/Ele/Rud 는 `:=` 100% 유지), UI 의 `스로틀 모드` 를
`offset` 으로 바꾼다. 그러면 PC 의 스로틀 채널은 1500µs 가 "변화 없음"이고, 조종사가 스틱으로 호버를 잡은 위에 PC 가
±`max_throttle_delta` 만 더한다. STANDBY/PANIC 도 오프셋 0 이라 조종사 스틱 그대로다. 트림 학습은 이 모드에서 꺼진다.
완전 자율 호버는 아니지만 "호버는 사람, 추적은 PC" 로 나누면 가장 안정적이다.

### 대안: Betaflight ALT_HOLD

FC 에 기압계(baro)가 있으면 Betaflight 2025.12 이상에서 `ALT_HOLD` 모드를 AUX 스위치에 걸어 펌웨어가 고도를 잡게 할 수
있다 (PC 스로틀은 중립 부근이면 유지). 1S AIO 보드는 대부분 baro 가 없으므로 Meteor75 Pro 2 의 FC 사양을 먼저 확인할 것.

## 세션 기록과 분석 (디버깅 구조)

**카메라가 연결되면 곧바로 자동 기록**이 시작된다 (`--auto-session always`, 기본). 조종기로 수동 이륙하는 구간과
SH 를 당기는 핸드오버 순간까지 전부 남기기 위해서다. 크래시로 영상이 깨져도 손실을 줄이려고 **5분마다 새 폴더로
분할**한다 (`--session-split-min`, 이벤트 `rollover`). 저장 위치는 `python/recordings/session_YYYYMMDD_HHMMSS/`.

- 도구 탭 `자동 기록`: `항상 (카메라 연결 시)` / `STANDBY 벗어날 때만` / `끔`. `R` 로 수동 중지하면 다시 `R` 을 누를 때까지
  자동 기록도 멈춘다.
- 용량: 720p 원본 약 0.9 MB/s, 1080p 약 2 MB/s (분당 ~120 MB). 오버레이 영상은 기본 **저장하지 않는다**
  (`--annotated-video` 로 켬). 리포트 도구가 raw.mp4 + frames.jsonl 로 오버레이를 다시 그리므로 필요 없다.
- 저장 폴더 여유가 1 GB 미만이면 기록하지 않고 상태 줄에 알린다.
- 매 프레임 **움직임 점수**(`motion`, 64x36 축소 영상의 프레임 차 평균, 0~1)를 남긴다. VRX 녹화 10분 실측: 기체가
  놓여 있을 때 중앙값 0.0003, 움직이는 구간 평균 0.02, 순간 최대 0.65. 리포트가 임계값(기본 0.015,
  `--motion-threshold`)으로 "움직임 구간"을 뽑아 긴 기록에서 비행 부분을 찾아 주고, 추적 구간이 없으면 격자 이미지도 이
  구간에서 고른다.

| 파일 | 내용 |
|---|---|
| `raw.mp4` | 오버레이 없는 원본 프레임 (제어 루프가 본 새 프레임을 정확히 1번씩 기록) |
| `annotated.mp4` | 오버레이 포함 (`--annotated-video` 일 때만) |
| `frames.jsonl` | 제어 스텝(30Hz)마다 1줄: 시각, `seq`/`det_seq`, `rec_frame`(raw.mp4 프레임 번호), 모드/상태, 움직임 점수, 모든 사람 박스, 트랙, 오차, PID 원출력/제한 후 출력, 채널 µs, 트림/학습 오프셋/하강량 |
| `events.jsonl` | 세션 시작/분할, 모드 전환, PANIC, 타깃 선택/해제, 트림 반영/초기화, 설정 변경(전체 설정 포함), 스냅샷 |
| `config.json` / `meta.json` | 설정 스냅샷, 소스·검출기·프레임 크기·git 해시·길이 |
| `shots/` | 스냅샷 PNG |

분석:

```powershell
cd python
python tools/session_report.py                       # 최신 세션 요약 (report.md 생성)
python tools/session_report.py <세션> --sheet 12 --plot --csv
#   sheet.png : TRACKING/LOST 구간에서 고르게 뽑은 12프레임 격자 (오버레이 재구성 + 시각/상태/스틱)
#   plot.png  : 스로틀·트림·err_y / yaw·err_x / pitch·err_size / 움직임 시계열 + 상태 색 띠 + 이벤트 선
#   frames.csv: 스프레드시트용
python tools/session_report.py <세션> --frames 12.5,40   # 특정 시각 프레임 PNG (원본 + 오버레이)
```

리포트에는 상태 비율, 추적 구간의 오차 평균/표준편차, 스로틀 min/max, 보정 포화 비율, err 부호 전환 횟수와 추정 진동 주기,
트림 학습 궤적, 상태 타임라인, 이벤트가 들어간다. 새 세션에서 "왜 이렇게 움직였나"를 볼 때는 `sheet.png` 와 `plot.png` 부터.

## PID 재튜닝 절차

1. 비행(또는 SITL) 세션을 만든다. 카메라 연결 중엔 항상 기록되므로 비행 후 카메라를 해제하거나 앱을 닫으면 폴더가 닫힌다
   (5분마다 자동 분할되니 문제 비행이 어느 폴더인지는 `meta.json` 의 시작 시각으로 찾는다).
2. `session_report.py <세션> --plot` 으로 진동/포화/부호를 본다.
   - err_y 부호 전환 주기가 1~2초로 짧고 스로틀이 ±폭을 오가면 → `throttle_kp` 를 줄이거나 `throttle_kd` 를 올린다.
   - err 가 한쪽에 오래 머무르고 스로틀이 포화(100% 근처)면 → 트림이 틀린 것. 트림부터 맞춘다.
   - yaw 가 계속 한쪽이면 → `invert_lateral`, 거리는 `invert_pitch`.
3. 같은 입력에 다른 게인을 적용해 보려면 (개루프, 기체 움직임은 반영 안 됨):

```powershell
python tools/session_replay.py <세션> --set throttle_kp=0.15 --set throttle_kd=0.12 --name kp015 --plot
python tools/session_replay.py <세션> --config examples/person_follow.json --plot     # 저장된 설정 전체로
python tools/session_replay.py <세션> --redetect --conf 0.4                            # raw.mp4 로 검출부터 다시
```

   `replay_<name>.png` 에 기록된 출력(회색)과 새 출력(빨강)이 겹쳐 그려지고, 요약에 두 출력의 차이·포화·진동이 나온다.
4. 마음에 드는 값을 UI 슬라이더에 넣고 `설정 저장` → 다음 비행.

## 운용 절차 (실기, props 있는 비행)

전제: Phase 5 (props off 검증) 완료, 트레이너 스위치(SH, 모멘터리) 동작 확인.

1. UI 실행 → 백엔드 `auto`(Pro Micro) 연결, 카메라 `UVC Camera` 연결. 모드는 STANDBY.
2. 조종기로 직접 이륙해 눈높이 정도에서 호버. 위의 "트림 맞추는 절차"로 `호버 스로틀` 을 찾는다.
3. UI 를 `2 HOVER` 로 두고 **SH 를 당긴다** → PC 트림으로 호버 유지되는지 확인. 불안하면 SH 놓기.
4. 사람이 화면에 들어온 상태에서 `3 FOLLOW`. 처음엔 `고도 보조` 와 `거리 유지` 를 끄고 yaw만 확인 → 하나씩 켠다.
5. 이상 시 **SH 놓기** 가 1순위 (즉시 조종기 스틱 복귀). `긴급 정지 · DISARM`(Space) 은 스로틀 최소 + AUX1 DISARM 이라
   공중에서는 추락한다 — 착지/비상 시에만 (offset 모드 스로틀은 예외지만 DISARM 은 모터를 끈다).

> ARM 은 설계 원칙상 조종기 물리 스위치에 두는 것이 안전하다. UI 의 ARM 버튼은 SITL 검증과 벤치 테스트(props off)용이며,
> 실기에서 PC ARM 을 쓰려면 EdgeTX Trainer 에 AUX1(CH5)까지 포함시켜야 한다. 기본 설계(스틱 4채널만 PC 제어)에서는
> AUX1 이 조종기로 안 넘어가므로 UI ARM 이 실기 기체를 ARM 하지 못한다 — 이때 표시는 `ARM SENT · 확인 불가` 로 정직하게 남는다.

초기 게인은 보수적으로 잡혀 있다 (yaw ±0.35, pitch ±0.25, 스로틀 ±0.12, 트림 학습 위로 +0.10).

## SITL 로 먼저 검증

```powershell
$ip = (wsl hostname -I).Trim().Split()[0]
python person_follow.py --camera "HD Webcam" --preset webcam720 --port sitl --sitl-host $ip
```

웹캠 앞에 사람이 서고 `SITL ARM` 체크 → HOVER → FOLLOW. Gazebo 에서 기체가 사람 쪽으로 yaw/pitch 하는지 확인한다.
고도 보조는 끄고 볼 것 (위 주의 참고). SITL 최초 1회 ARM 설정은 [sitl-gazebo.md](sitl-gazebo.md) 참고.

## 테스트

```powershell
cd python
python -m pytest tests -q
```

PID, 트래커, 컨트롤러 부호/한계/트림 학습/offset 모드, 상태 전이/LOST 하강, 스로틀 슬루, RF-DETR 디코딩,
세션 기록·리포트·리플레이는 하드웨어·모델 없이 검증된다.

# 프로젝트 계획 & 진행 상황

PC → Pro Micro → TX15 Max(트레이너) → ELRS → Betaflight 관제 체인 구축.
설계 원칙: PC는 스틱 4채널만 제어, ARM·모드 스위치는 조종기 유지.

## Phase 1 — 하드웨어 배선 ✅ 완료

- Pro Micro **D10** → 3.5mm 플러그 **L(팁)**, GND → 접지(슬리브), R(링) 비움
- 나사조임식 3.5mm 플러그 + 암-수 점퍼선으로 무납땜 조립
- 상세: [wiring.md](wiring.md)

## Phase 2 — Pro Micro 펌웨어 ✅ 완료

- `firmware/promicro_ppm/`: USB 시리얼(115200) → PPM 변환, 500ms 타임아웃 페일세이프
- 보드 클럭 실측 판별(틱 간격 0.998~1.001초) → **5V/16MHz 확정**, 업로드 완료 (COM11)

## Phase 3 — Python 라이브러리 ✅ 완료

- `python/buddybox/`: 50Hz 송신, 포트 자동 탐지, 정규화 스틱 API
- `python/examples/`: 수동 조종 GUI(manual_control.py), 스윕 테스트(channel_sweep.py)
- PC → Pro Micro 시리얼 경로 + 타임아웃 페일세이프 검증 완료

## Phase 4 — TX15 Max 설정 🔄 진행 중

- [x] 모델 Trainer 모드 = `Master/Jack`
- [x] SYS → Trainer: 4채널 Replace / CH1~4 / 100% 확인
- [x] 스윕 신호 수신 확인 (TRAINER 화면에서 Ail/Ele/Rud 값 왕복 확인됨)
- [ ] **캘리브레이션** — PC가 전 채널 1500µs 송신 중에 Calibration 버튼 누르기
- [ ] **트레이너 활성화 스위치** — Special Functions에 SH(모멘터리) → Trainer 등록
- 상세: [radio-setup.md](radio-setup.md)

## Phase 5 — Betaflight 검증 ⬜ 예정 (props off!)

- [ ] Configurator Receiver 탭에서 4채널 방향·범위(988~2012) 확인, 채널맵 AETR
- [ ] 페일세이프 3종 테스트: 시리얼 강제 종료 / 트레이너 스위치 해제 / USB 분리
- [ ] 프롭 제거 상태 ARM + 모터 반응 확인
- 체크리스트: [radio-setup.md](radio-setup.md) 5번 항목

## Phase 6 — 실제 제어 로직 연동 ⬜ 예정

- [x] 안전 필터 계층 (`buddybox/safety.py` SafetyLimiter — 기울기·스로틀·슬루레이트 제한)
- [ ] PC 쪽 자동 제어(비전 등)와 buddybox 라이브러리 연결

## 인프라

- [x] 단위 테스트 (`python/tests/` — 프로토콜 인코딩, 안전 필터, 14개)
- [x] GitHub Actions CI (푸시마다 펌웨어 컴파일 + 테스트 자동 실행)

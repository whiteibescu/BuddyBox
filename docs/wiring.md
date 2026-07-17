# 배선 가이드 — Pro Micro ↔ TX15 Max DSC 포트

## 준비물

- Pro Micro (ATmega32U4) — **본 프로젝트 보드: 5V/16MHz 확정** (5V 버전은 항상 16MHz)
- 3.5mm 수(male) 플러그 케이블 (TS 모노 / TRS 스테레오 모두 가능)
- Micro-USB 케이블 (PC ↔ Pro Micro)

## 배선

3.5mm 플러그 기준:

```
Pro Micro D10  ────────────  팁 (Tip)      → PPM 신호
Pro Micro GND ────────────  슬리브 (Sleeve) → GND
                            링 (Ring)      → 미사용 (TRS인 경우)
```

| Pro Micro 핀 | 3.5mm 플러그 | 역할 |
|---|---|---|
| D10 | Tip (끝부분) | PPM 출력 |
| GND | Sleeve (뿌리 쪽) | 접지 |
| — | Ring (중간, TRS만) | 연결 안 함 |

> **권장**: 5V 보드이므로 D10와 Tip 사이에 **1kΩ 저항 하나를 직렬로** 넣으면
> 조종기 입력 핀을 보호할 수 있습니다. EdgeTX 조종기 트레이너 입력은 보통
> 5V 신호도 견디지만, 저항 하나면 확실한 보험이 됩니다. (없어도 대부분 동작)

> **주의**: Tip과 Sleeve를 헷갈리면 신호가 인식되지 않습니다.
> Sleeve는 플러그의 가장 뿌리(케이블 쪽) 부분입니다.

## Pro Micro 버전 확인 (5V/16MHz vs 3.3V/8MHz)

PPM 신호 자체는 3.3V든 5V든 TX15 Max 트레이너 입력이 인식하므로 배선은 동일합니다.
단, **Arduino IDE에서 보드 클럭을 잘못 선택하면 PPM 타이밍이 2배 어긋나므로** 반드시 확인하세요.

확인 방법 (쉬운 순서):

1. **보드 뒷면 표기** — "5V 16MHz" 또는 "3.3V 8MHz" 실크 인쇄 확인
2. **J1 점퍼** — 레귤레이터 근처 J1 점퍼가 납땜으로 연결되어 있으면 5V 직결(보통 5V 버전)
3. **판별 스케치** — 업로드 후 LED 깜빡임 속도로 판별:
   - 16MHz 보드에 8MHz 설정으로 업로드하면 깜빡임이 2배 빠름 (그 반대는 2배 느림)
   - `firmware/clock_check/clock_check.ino` 참고: 정확히 1초 간격으로 깜빡이는 쪽이 올바른 설정

Arduino IDE 보드 설정 (5V/16MHz 보드 기준):
- 보드: **Arduino Leonardo** (기본 16MHz라 그대로 사용 가능)
- 또는 SparkFun 보드 매니저 설치 후 **SparkFun Pro Micro** + Processor **ATmega32U4 (5V, 16MHz)**

## 연결 순서

1. Pro Micro에 펌웨어 업로드 (`firmware/promicro_ppm/`)
2. 3.5mm 케이블을 Pro Micro에 배선 (위 표 참조)
3. TX15 Max 전원 켜고 모델 설정에서 Trainer 모드 활성화 (→ `docs/radio-setup.md`)
4. 3.5mm 플러그를 TX15 Max 상단 **DSC 포트**에 삽입
5. PC에서 Python 테스트 스크립트 실행

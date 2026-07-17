# 질문 & 답변 로그

프로젝트를 진행하며 나온 질문을 한 문장씩 기록한다. (최신이 아래)

## 2026-07-16

- **Q. TX15 Max의 student/teacher 기능으로 PC에서 ELRS→Betaflight까지 관제하려면 어떻게 구성하나?**
  → PC(Python) → Pro Micro(시리얼→PPM 변환) → DSC 트레이너 포트 → EdgeTX Trainer 믹싱 → 내장 ELRS → Betaflight 순의 체인으로 구성한다.

- **Q. 구입한 Pro Micro가 5V인지 3.3V인지 보드에 둘 다 적혀 있는데 어떻게 구분하나?**
  → 클론 보드는 공용 기판이라 둘 다 인쇄되어 있으므로, 1초 깜빡임 테스트(또는 크리스탈 각인, 멀티미터)로 판별해야 한다.

- **Q. 클럭 확인은 어떻게 하나?**
  → 16MHz 설정으로 컴파일한 스케치가 정확히 1초 간격으로 동작하면 16MHz 보드이며, 실측 결과 0.998~1.001초로 5V/16MHz 확정됐다.

## 2026-07-17

- **Q. 점퍼선을 꽂는 핀의 위치가 다이어그램과 달라도 되나?**
  → 다이어그램 위치는 개념도일 뿐이고 보드에 인쇄된 글자(10, GND)를 보고 꽂으면 되며, GND는 3개 중 아무거나 써도 된다.

- **Q. 3.5mm 나사조임식 플러그에 L/R 화살표가 있는데 어디에 연결하나?**
  → L = 팁(신호선, 10번 핀), 접지 표기 단자 = 슬리브(GND)이고 R(링)은 비워둔다.

- **Q. 점퍼선 색깔이 달라도 되나?**
  → 색은 사람이 구분하기 위한 관례일 뿐이며 어느 핀에서 어느 단자로 이어지는지만 맞으면 된다.

- **Q. EdgeTX TRAINER 화면의 Ail 0, Ele 6, Thr 582, Rud -2는 무슨 뜻인가?**
  → 학생(PC)이 보낸 Roll/Pitch/Throttle/Yaw 입력값으로, 범위는 약 -512(끝)~0(중앙)~+512(반대 끝)이며 잔값은 Calibration으로 0에 맞춘다.

- **Q. 왜 이름이 Ail/Ele/Thr/Rud인가?**
  → RC 조종기가 비행기에서 출발해 조종면 이름(Aileron/Elevator/Throttle/Rudder)을 그대로 쓰며, 드론에서는 각각 Roll/Pitch/모터출력/Yaw에 해당한다.

- **Q. .gitignore가 필요할까?**
  → 파이썬이 자동 생성하는 `__pycache__` 캐시 같은 파일이 커밋에 섞이는 것을 막기 위해 필요하다.

- **Q. 커밋·푸시·PR은 어떻게 진행됐나?**
  → `feature/buddybox-ppm-bridge` 브랜치로 커밋 후, GitHub 자격증명을 whiteibescu 계정으로 재로그인해 푸시하고 [PR #1](https://github.com/whiteibescu/BuddyBox/pull/1)을 생성했다.

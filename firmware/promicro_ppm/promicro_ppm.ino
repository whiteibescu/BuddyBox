/*
 * BuddyBox — USB Serial to PPM trainer signal generator
 *
 * Board  : Pro Micro (ATmega32U4, 5V/16MHz or 3.3V/8MHz — F_CPU 기반 자동 보정)
 * Output : D10 → 3.5mm 잭 Tip (TX15 Max DSC 트레이너 포트), GND → Sleeve, Ring 미사용
 *
 * Serial protocol (115200 baud, 19-byte frame):
 *   [0] 0xA5  [1] 0x5A  header
 *   [2..17]   8 × uint16 little-endian, channel pulse width in µs (988..2012)
 *   [18]      XOR checksum of bytes [2..17]
 *
 * Safety: 시리얼 프레임이 SIGNAL_TIMEOUT_MS 동안 없으면 PPM 출력을 정지한다.
 * EdgeTX는 트레이너 신호 상실로 판단하고 즉시 조종기 스틱으로 복귀한다.
 */

#define PPM_PIN            10      // D10 → 3.5mm Tip
#define PPM_CHANNELS       8
#define PPM_FRAME_US       22500   // 프레임 길이
#define PPM_PULSE_US       300     // 채널 구분 펄스 폭
#define PPM_PULSE_LEVEL    HIGH    // 펄스 극성 (HIGH 펄스 / LOW 유휴). 인식 안 되면 LOW로 변경
#define SIGNAL_TIMEOUT_MS  500

#define CH_MIN_US          988
#define CH_MAX_US          2012
#define CH_MID_US          1500

// Timer1, prescaler 8: 16MHz → 2 tick/µs, 8MHz → 1 tick/µs
#define US_TO_TICKS(us)    ((uint16_t)((us) * (F_CPU / 8000000UL)))

volatile uint16_t channels[PPM_CHANNELS];   // µs 단위
volatile bool ppmEnabled = false;

uint8_t rxBuf[19];
uint8_t rxPos = 0;
unsigned long lastFrameMs = 0;

void setup() {
  for (uint8_t i = 0; i < PPM_CHANNELS; i++) channels[i] = CH_MID_US;
  channels[2] = CH_MIN_US;  // CH3 (Throttle) 은 최저로 초기화

  pinMode(PPM_PIN, OUTPUT);
  digitalWrite(PPM_PIN, !PPM_PULSE_LEVEL);  // 유휴 레벨

  Serial.begin(115200);

  // Timer1: CTC 모드, prescaler 8
  noInterrupts();
  TCCR1A = 0;
  TCCR1B = _BV(WGM12) | _BV(CS11);
  OCR1A  = US_TO_TICKS(PPM_FRAME_US);
  interrupts();
}

// PPM 상태 머신: 펄스(300µs) ↔ 채널 간격을 번갈아 출력
ISR(TIMER1_COMPA_vect) {
  static bool inPulse = false;
  static uint8_t ch = 0;
  static uint16_t frameRemaining = 0;

  if (!ppmEnabled) {
    digitalWrite(PPM_PIN, !PPM_PULSE_LEVEL);
    inPulse = false;
    ch = 0;
    OCR1A = US_TO_TICKS(PPM_FRAME_US);
    return;
  }

  if (!inPulse) {
    // 펄스 시작
    digitalWrite(PPM_PIN, PPM_PULSE_LEVEL);
    OCR1A = US_TO_TICKS(PPM_PULSE_US);
    inPulse = true;
  } else {
    // 펄스 종료 → 채널 나머지 시간 또는 동기 갭
    digitalWrite(PPM_PIN, !PPM_PULSE_LEVEL);
    inPulse = false;
    if (ch == 0) frameRemaining = PPM_FRAME_US;

    if (ch < PPM_CHANNELS) {
      uint16_t width = channels[ch];
      frameRemaining -= width;
      OCR1A = US_TO_TICKS(width - PPM_PULSE_US);
      ch++;
    } else {
      // 동기 갭: 프레임 잔여 시간
      OCR1A = US_TO_TICKS(frameRemaining - PPM_PULSE_US);
      ch = 0;
    }
  }
}

void applyFrame() {
  noInterrupts();
  for (uint8_t i = 0; i < PPM_CHANNELS; i++) {
    uint16_t v = rxBuf[2 + i * 2] | ((uint16_t)rxBuf[3 + i * 2] << 8);
    channels[i] = constrain(v, CH_MIN_US, CH_MAX_US);
  }
  interrupts();
  lastFrameMs = millis();

  if (!ppmEnabled) {
    ppmEnabled = true;
    noInterrupts();
    TCNT1 = 0;
    TIMSK1 = _BV(OCIE1A);   // PPM ISR 시작
    interrupts();
  }
  RXLED1;  // 프레임 수신 표시 (수신 LED 켬)
}

void loop() {
  while (Serial.available()) {
    uint8_t b = Serial.read();
    if (rxPos == 0 && b != 0xA5) continue;
    if (rxPos == 1 && b != 0x5A) { rxPos = 0; continue; }
    rxBuf[rxPos++] = b;
    if (rxPos == sizeof(rxBuf)) {
      rxPos = 0;
      uint8_t sum = 0;
      for (uint8_t i = 2; i < 18; i++) sum ^= rxBuf[i];
      if (sum == rxBuf[18]) applyFrame();
    }
  }

  // 페일세이프: 프레임 타임아웃 → PPM 정지 (EdgeTX가 스틱으로 복귀)
  if (ppmEnabled && millis() - lastFrameMs > SIGNAL_TIMEOUT_MS) {
    ppmEnabled = false;
    RXLED0;  // 수신 LED 끔
  }
}

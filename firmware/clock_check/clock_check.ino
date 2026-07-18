/*
 * Pro Micro 클럭 판별 스케치
 *
 * 업로드 후 온보드 LED(TX LED)가 "정확히 1초 간격"으로 깜빡이면
 * Arduino IDE에서 선택한 보드 클럭(16MHz/8MHz)이 실제 보드와 일치하는 것.
 *
 * - 2배 빠르게 깜빡임 → 실제는 8MHz 보드인데 16MHz로 컴파일됨
 * - 2배 느리게 깜빡임 → 실제는 16MHz 보드인데 8MHz로 컴파일됨
 */

void setup() {}

void loop() {
  TXLED1;
  delay(1000);
  TXLED0;
  delay(1000);
}

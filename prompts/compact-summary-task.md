# 새 요약 카드 구현 작업

사용자가 전달한 `engineering-harness.md`를 기준으로 탐색 → 구현 → 격리 환경 검증 → 결과 확인 순서로 진행한다.

## 목표와 제약

- 참고 이미지의 역할군·영웅 이름표·간결한 수치 표현을 자동 생성 코드에 적용한다.
- 영웅·기술·단위·특전·모드·부정 표현을 보존한다. 불확실한 방향은 조정으로 표시한다.
- 공식 본문 이미지 전송 제외와 본문 중복 방지를 유지한다.
- 운영 `state.json`을 초기화하지 않는다. 카드 버전을 올려 이전 카드 이미지만 갱신한다.
- 로컬에서는 탐색과 편집을 수행한다. 테스트와 이미지 렌더링은 GitHub Actions의 격리된 Ubuntu runner에서 수행한다. 테스트용 HTTP 호출은 mock 처리하고 실제 Discord 메시지를 보내지 않는다.

## 수용 기준과 증거

1. `tests/test_compact_text.py`: 전후 값, 변화량, 소수, 단위, 조건, 부정 표현과 강조 범위 검증.
2. `tests/test_summary.py`: 역할 계층, 개별 방향, 혼합 조정, 영웅 변경 8줄 제한 제거 검증.
3. `tests/test_card_layout.py`: 짧은 카드 높이, 긴 목록과 단일 문장의 페이지 분할, 누락 없는 내용, PNG 생성 검증.
4. `tests/test_delivery.py`: 기존 메시지 수정, 실패 후 재개, 이미지 제외, 카드 버전 갱신 시 본문 중복 전송 방지 검증.
5. CI에서 `python -m unittest discover -s tests -v` 실행 후 `python scripts/render_card_samples.py`로 예시를 만든다.
6. `summary-card-previews` 아티팩트의 PNG를 열어 글자 겹침·잘림·강조·역할군 배치를 확인한다. 테스트 로그와 검토한 실행 링크는 최종 PR에 기록한다.

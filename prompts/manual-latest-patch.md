# 수동 실행은 최신 패치 한 개만 처리

- 사용자 요청: Actions의 수동 Run workflow가 과거 패치까지 Discord에 올려 혼잡하므로 최신 패치 하나만 처리한다.
- 두 check-patch.yml 파일에 `LATEST_PATCH_ONLY`를 연결한다. `workflow_dispatch`이면 true, 예약 실행이면 false다.
- 수집·출처 중복 제거·동일 날짜 순서 ID 부여는 전체 목록에서 완료한다. 이후 날짜와 같은 날 순서가 가장 큰 패치 하나만 실제 전송/수정/요약 카드 갱신 및 DRY_RUN 대상으로 선택한다.
- 기존 상태 이관 및 첫 실행의 과거 기준선 기록에는 전체 목록을 유지한다. 수동 실행 때문에 이후 예약 실행에서 과거 기록을 잃지 않게 한다.
- 최신 패치가 이미 전송됐으면 중복 전송하지 않으며 영어이면 한국어판을 기다린다. 오래된 글로 대체하지 않는다. 패치 한 개가 Discord 메시지 한 개라는 의미는 아니다.
- 예약 실행의 처리 범위는 변경하지 않는다. 운영 state.json을 초기화하지 않는다.
- `engineering-harness.md`에 따라 GitHub Actions의 격리된 Ubuntu runner에서 전체 테스트를 수행한다. tests/test_manual_scope.py에서 실제 main/process_patch 흐름을 확인하며 Discord 전송과 수집은 mock으로 차단한다.

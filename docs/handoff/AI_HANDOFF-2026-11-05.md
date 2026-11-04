# 오버워치 패치 봇 인수인계

작성일: 2026-11-05, 한국 시간 기준.

## 현재 상태와 다음 작업

사용자는 수정본을 오류 검사한 뒤 GitHub에 올려 달라고 요청했다. 로컬 구현·테스트·커밋은 끝났지만 GitHub에 업로드하지 못했다. 새 컴퓨터에서 이 작업을 이어서 완료하면 된다.

- 저장소: https://github.com/wldnjs826/overwatch-patch-bot
- 운영 브랜치: `main`
- 수정 기준 커밋: `d2d0b5af24280cb2985492e8884b09ea31f6c05c`
- 로컬 수정 커밋: `14df3bdc9cf2c11ff9aafe18fdaa7e3e61de5533`
- 로컬 브랜치: `codex/free-balance-classification`
- 커밋 제목: `Improve offline balance classification and automatic fallback cards`
- 패키지 작성 시 원격 main은 기준 커밋과 같았다. 새 환경에서는 반드시 다시 확인한다.
- 실제 업로드는 수행되지 않았다. `git push --dry-run`이 인증 부재로 실패했으며, 브라우저 대체 경로도 현재 URL 확인 실패로 도구가 중단했다. 코드 검사 실패가 아니다.

이 문서는 작업 맥락과 적용 안내다. GitHub 인증은 새 컴퓨터의 정상 로그인 절차를 사용한다.

## 사용자가 원하는 동작

오버워치 공식 패치 노트를 자동으로 수집하고, 한국어 원문과 요약 카드를 Discord로 보낸다. 사용자는 매 패치마다 버프·너프를 직접 분류할 수 없으며, 유료 AI API 비용도 원하지 않는다.

따라서 외부 AI API를 추가하지 않았다. 기존 규칙을 보완해 확실한 항목은 자동 분류하고, 방향을 확정하기 어려운 항목은 원문을 그대로 담은 `변경 사항` 카드로 자동 전송한다. 수동 입력이나 확인을 기다리지 않는다. 모든 변경을 완벽하게 버프·너프로 나눌 수 있다고 주장하지 않는다.

특전 변경은 기존 사용자 규칙에 따라 수치 방향과 무관하게 항상 `조정`이다. 일반 모드와 스타디움의 판정은 서로 분리한다.

## 구현 내용

1. `balance_context.py`를 추가했다. 모드·영웅·기술·수치 항목이 모두 일치할 때만 적용하는 무료 규칙 7개다. 겐지 튕겨내기 지속 시간, 엠레 수류탄 폭발 시간, 벤데타 도약 속도, 제트팩 캣 가속도, 솜브라 기술 2개, 스타디움 벤데타 처치 요구 횟수를 다룬다. 특정 패치의 전후 숫자를 외우지 않고 해당 수치가 커지거나 작아졌을 때의 이득 방향을 판정하므로 다음 패치의 다른 숫자에도 적용된다. 근거는 파일 상단의 공식 출처에 기록했다.
2. `monitor.py`의 `classify_change_line`에 영웅·모드 문맥을 전달했다. 문장을 여러 절로 나눈 경우와 카드 내부 행의 화살표 계산에도 같은 문맥을 전달한다. 부정 표현, 서로 비교할 수 없는 단위, 다른 영웅·모드·기술에는 규칙을 잘못 적용하지 않도록 테스트했다.
3. UI·조준선 변경을 표현 변경으로 구분했다. 치유 기술 이름이 UI 추적 설명에 등장해도 실제 치유량 변경과 혼동하지 않게 처리한다.
4. `돌격 영웅`, `공격 영웅`, `지원 영웅`, `Support Heroes` 같은 공식 역할 제목도 인식한다.
5. 미분류 항목은 내부 식별자 `review`를 유지하되 카드 표시는 `판별 필요 / ?`에서 `변경 사항 / •`로 바꿨다. 원문 문장을 보존하며 확실한 버프·너프와 따로 전송한다. 표현 변경만 있으면 기존 `기타 변경` 분류를 유지한다.
6. `SUMMARY_CARD_VERSION`을 5에서 6으로 올렸다. 실제 적용 시 처리 대상 최신 패치의 구버전 카드가 갱신될 수 있다.
7. 테스트 9개와 카드 예시를 추가했다. 기존 96개를 포함해 총 105개 테스트가 통과했다.
8. README와 작업 기준 문서를 실제 코드에 맞게 수정했다. 예약·수동 실행 모두 최신 패치 하나만 처리하며, 전송 완료 기록에 원문 메시지 ID가 없으면 자동 재전송하지 않는다. `LATEST_PATCH_ONLY=false`로도 제한이 해제되지 않는 현재 동작을 설명했다.

변경된 파일은 `changes/` 아래의 11개다. 실행 코드 3개(`monitor.py`, `summary_cards.py`, 신규 `balance_context.py`), 테스트 1개, 예시 렌더러 1개, 문서 6개로 구성된다. 의존성 파일과 워크플로, 운영 상태 파일은 변경하지 않았다.

## 코드 구조

- `monitor.py`: 넥슨·블리자드 수집, 본문 파싱, 한국어 판별, 중복 확인, 최신 패치 선택, 분류, Discord 전송·수정, 상태 저장.
- `balance_context.py`: 문맥이 필요한 수치 항목의 이득 방향 규칙.
- `summary_text.py`: 수치·단위·조건을 보존하며 문장을 짧게 표기.
- `summary_cards.py`: 모드·분류·역할별 카드 배치와 Pillow PNG 생성.
- `state.json`: 운영 전송 이력, 메시지 ID, 해시, 카드 버전. 원격 최신본을 보존해야 한다.
- `.github/workflows/check-patch.yml`: 실제 예약 감시. 최상위 `check-patch.yml`은 참고용 복사본이며 서로 같아야 한다.
- `.github/workflows/tests.yml`: Python 3.12 / Ubuntu의 회귀 테스트와 오프라인 카드 생성.
- `test_latest.py`: 단위 테스트가 아니라 실제 Discord 테스트 전송 도구다. 상태를 읽지 않고 전송하므로 오류 검사 용도로 실행하지 않는다.

## 패치 적용

먼저 저장소의 `AGENTS.md` 등 해당 환경의 작업 지침, 작업 트리 상태, 원격 주소를 확인한다. 기존 변경이 있으면 보존하고 별도 작업 트리나 새 복제본에서 작업한다.

1. 최신 원격 코드를 가져온다. 새 복제본을 쓴다면 아래처럼 시작한다.

```sh
git clone https://github.com/wldnjs826/overwatch-patch-bot.git
cd overwatch-patch-bot
git fetch origin
git status --short
git log -1 --oneline origin/main
git switch -c codex/free-balance-classification origin/main
```

같은 이름의 브랜치가 이미 있으면 내용을 확인해 재사용하거나 새 이름을 선택한다. 기존 브랜치를 강제로 덮어쓰지 않는다. 로컬 수정 커밋이 원격에 없으므로 원격에서 그 커밋 번호만 cherry-pick하려고 하지 않는다.

2. 패키지의 패치를 적용한다. `PATCH_PATH` 대신 압축을 푼 실제 절대 경로를 사용한다. Git 커밋 작성자 설정이 필요하면 해당 환경의 기존 설정이나 허용된 봇 식별자를 사용한다.

```sh
git am --3way "PATCH_PATH/0001-offline-balance-classification.patch"
```

이 패치는 새 파일도 포함한다. 적용 전에 같은 기능이 이미 반영됐는지 확인해 중복 적용하지 않는다. `git am`에 의해 새 환경의 커밋 해시가 달라질 수 있지만 파일 내용과 검사 결과가 기준이다.

3. 원격 코드가 진전되어 충돌하면 충돌 파일의 최신 기능을 보존하며 수정하고, 해결한 파일만 stage한 뒤 `git am --continue`로 마무리한다. 자동 병합이 적절하지 않으면 `git am --abort` 후 `changes/`와 패치를 참고해 같은 변경을 수동으로 옮긴다. `changes/` 전체를 무조건 덮어써서 원격의 새 코드를 잃지 않도록 한다.

운영 `state.json`은 패키지에 넣지 않았다. 삭제·초기화하거나 예전 파일로 덮어쓰면 중복 전송이 발생할 수 있으므로 최신 원격본을 유지한다. Discord 웹훅 비밀값은 기존 GitHub Secret을 그대로 사용하며 새 AI API 키는 필요 없다.

## 오류 검사

운영 CI와 맞추려면 Python 3.12를 우선 사용한다. 기존 로컬 검사는 Windows / Python 3.14.3에서 수행됐다. GitHub Actions / Python 3.12 검사는 업로드가 막혀 아직 실행하지 못했으므로 새 환경에서 CI까지 확인해야 한다.

가상환경에 의존성을 설치하고 해당 가상환경의 Python으로 실행한다.

```sh
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q monitor.py balance_context.py summary_text.py summary_cards.py test_latest.py scripts tests
python scripts/render_card_samples.py
git diff --check
git diff origin/main...HEAD -- state.json requirements.txt .github/workflows check-patch.yml
```

한글 폰트가 필요하다. Windows는 맑은 고딕, Ubuntu는 `fonts-noto-cjk`를 사용한다. 마지막 diff는 원래 변경 범위에 운영 상태·의존성·워크플로가 포함되지 않았음을 확인하는 용도다. 새 원격 변경과 비교해 내용을 해석한다.

기준 결과: 테스트 105개 통과, 문법 검사 정상, 10개 예시에서 총 77장 PNG 생성. `card-previews/free-context/`의 상향·하향·변경 사항 카드에서 한글, 수치, 화살표, 잘림 여부를 확인한다. 실제 Discord 요청은 테스트에서 mock 처리한다.

사이트 수집 확인이 꼭 필요하면 `DRY_RUN=true`로만 `monitor.py`를 실행한다. PowerShell 예: `$env:DRY_RUN = "true"; python monitor.py; Remove-Item Env:DRY_RUN`. 수동 실제 전송은 사용자가 별도로 원할 때 진행한다.

## GitHub 반영과 완료 확인

로그인 수단이 있는지 확인한다. GitHub CLI를 쓰면 `gh auth status` / `gh auth login`, Windows Git Credential Manager를 쓰면 `git credential-manager github login`을 사용할 수 있다. 비밀번호나 토큰을 채팅으로 요청하지 않는다.

```sh
git push -u origin HEAD
```

`codex/**` 브랜치 업로드는 회귀 테스트 워크플로를 실행한다. GitHub CLI가 있으면 `gh run list --branch <작업브랜치> --workflow tests.yml`로 이번 커밋의 실행을 찾고 `gh run watch <실행ID> --exit-status`로 결과를 확인한다. 오래된 커밋의 성공 결과를 이번 검사로 오인하지 않는다. 없으면 GitHub Actions UI나 사용 가능한 GitHub 도구로 확인한다.

검사가 통과하면 사용자가 요청한 실제 봇 반영을 완료한다. `main` 직접 반영이 허용되면 원격을 다시 가져와 최신 main 변경을 보존한 상태로 정상 push한다. 예약 실행이 `state.json`을 갱신해 원격이 진전될 수 있으므로 필요하면 rebase/병합한 뒤 다시 확인한다. 강제 push는 하지 않는다. 브랜치 보호가 있으면 PR을 만들고 해당 저장소 절차를 따른다.

최종적으로 원격의 반영 커밋, 파일 내용, GitHub Actions 결과를 확인한다. 브랜치에만 올라간 상태와 main에 반영된 상태를 구분해 사용자에게 알려준다. 인증이나 권한 때문에 완료할 수 없으면 구체적인 미완료 지점을 알린다. 업로드만 시도하고 완료됐다고 보고하지 않는다.

## 이후 수정 시 참고

- 새로운 문맥 규칙은 공식 근거가 있는 경우에만 추가한다. 같은 영웅이라도 모드·기술·항목이 다르면 재사용하지 않는다.
- 수치의 증가·감소와 실제 이득 방향을 구분한다. 단위 불일치·부정문·수치 감소량·피해를 주는지 받는지 같은 차이를 보존한다.
- 특전은 항상 조정이라는 사용자 규칙을 유지한다.
- 애매한 항목도 원문을 보존하며 자동 발송한다. 다시 수동 확인을 필수로 만들거나 유료 API를 추가하지 않는다.
- 카드 표시·분류 결과가 바뀌어 기존 카드를 갱신해야 하면 `SUMMARY_CARD_VERSION`과 문서를 함께 갱신한다. 과거 패치까지 다시 보내는 제한 해제는 하지 않는다.
- README와 `prompts/`의 오래된 설명이 새 코드와 충돌하지 않는지 확인한다.

## 증거와 한계

`verification/local-tests.txt`, `verification/card-render.txt`, `verification/summary.json`, `verification/package-apply.txt`를 참고한다. 카드 미분류 감소는 저장해 둔 공식 게시물 한 건에서 측정한 결과로, 전체 패치에 대한 정확도 수치가 아니다.

공식 게시물: https://overwatch.nexon.com/news/patchnotes/858/patch-2026-11-03
2026-11-05에 가져온 본문 제목은 2026년 11월 4일 패치였다. 변경 항목 54개 중 미분류가 기존 17개에서 4개로 줄었다. 남은 항목은 버프·너프를 억지로 확정하지 않고 변경 사항 카드로 자동 전달한다.

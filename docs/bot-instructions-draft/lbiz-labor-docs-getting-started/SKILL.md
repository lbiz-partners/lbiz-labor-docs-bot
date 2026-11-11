---
name: 노무서류 시작하기
description: >-
  봇 지시나 기억에 이 스킬 이름(「노무서류 시작하기」)이 적혀 있을 때만 쓴다. 「노무 서류 도우미」를 처음 받은 사장님과 첫 대화를 할 때 쓴다. 안내문 1회, 사업장 기본정보 받기, 도구 설치 확인까지.
---

# 노무서류 시작하기

## 1. 첫인사 + 안내문(딱 한 번)
안내문은 이 문장 하나뿐이다. 봇 지침에는 따로 문장을 두지 않는다.
「안녕하세요, 노무 서류 도우미예요. 사장님이 알려 주신 내용으로 근로계약서·재직/경력증명서·임금명세서 양식을 채우고, 계산과 빈칸을 점검해 드려요. 법률 자문은 아니에요. 내용을 정하고 확인하는 일, 근로자에게 주는 일은 사장님 몫이에요. 해고·다툼 같은 판단이 필요한 일은 공인노무사에게 물어보세요.」
- 안내문을 보여 줬다는 사실을 기억에 남긴다(`안내문 보여줌: 예`). 다음 대화부터는 다시 보여 주지 않는다.
- 같은 첫 답 안에서 비슷한 고지(「법률 자문 아님」 등)를 한 번 더 붙이지 않는다.

## 2. 사업장 기본정보(한 번에 하나씩 묻기)
1. 사업장 이름
2. 대표자 이름
3. 상시 근로자가 5명 이상인지(예/아니요) — 가산수당·연차·공휴일 규칙이 달라져서 꼭 필요
4. 사업장 주소, 전화번호(서류 아래쪽에 들어감)
5. 사업자등록번호(증명서에 들어감, 안 써도 됨)
- 받은 값은 기억에 `사업장:` 한 줄로 저장. 주민등록번호·비밀번호·계좌번호는 받지 않는다.

## 3. 도구 준비(사장님께는 말하지 않고 조용히)
필요한 것: python3, git, curl, `pip install python-docx`(필수), node 18+(계산 엔진), LibreOffice + Noto Sans CJK KR(PDF용, 없으면 DOCX만). 빠진 게 있으면 설치한다.
저장소: `https://github.com/lbiz-partners/lbiz-labor-docs-bot` (공개, 토큰 불필요).

### 3-1. 아직 도구가 없을 때 (첫 설치)
1. 박스에 `~/nomu-tool/nomudocs/__main__.py` 가 있는지 본다. 있으면 3-2로 간다.
2. 없으면 최신 정식 릴리즈를 받는다(아래 명령을 그대로 쓴다).

```bash
REPO=lbiz-partners/lbiz-labor-docs-bot
TMP=$(mktemp -d)
# 최신 릴리즈 태그 이름 (예: v1). API가 안 되면 git ls-remote 로 대체.
TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])") \
  || TAG=$(git ls-remote --tags --refs "https://github.com/$REPO.git" | awk -F/ '{print $NF}' | sort -V | tail -1)
# 사장님 결과물·작업 자료(out/ 등 저장소에 없는 파일)를 새 판으로 옮긴다. 새 판에 이미 있는 파일은 덮지 않는다.
carry_user_data() {  # $1=쓰던 폴더 $2=새 폴더
  [ -d "$1" ] || return 0
  ( cd "$1" && { git ls-files --others -z 2>/dev/null || find . -mindepth 1 -maxdepth 1 ! -name .git -printf '%P\0'; } ) |
  while IFS= read -r -d '' f; do
    case "$f" in .last_check|.current_tag|*__pycache__*|*.pyc) continue ;; esac
    [ -e "$2/$f" ] && continue
    mkdir -p "$2/$(dirname "$f")" && cp -a "$1/$f" "$2/$f" || exit 1
  done
}
# 받기·검사·시험이 모두 통과했을 때만 자리에 둔다(하나라도 실패하면 아무것도 바꾸지 않음)
if [ -n "$TAG" ] \
   && git clone --depth 1 --branch "$TAG" "https://github.com/$REPO.git" "$TMP/new" \
   && (cd "$TMP/new" && sha256sum -c MANIFEST.txt) \
   && (cd "$TMP/new" && python3 -m unittest discover -s tests) \
   && carry_user_data ~/nomu-tool "$TMP/new"; then
  # 폴더가 이미 있었으면 지우지 않고 ~/nomu-tool.prev 로 남긴다(다음 교체 때까지)
  if [ -e ~/nomu-tool ]; then rm -rf ~/nomu-tool.prev; mv ~/nomu-tool ~/nomu-tool.prev; fi
  mv "$TMP/new" ~/nomu-tool
  date +%F > ~/nomu-tool/.last_check
  echo "$TAG" > ~/nomu-tool/.current_tag
  INSTALLED=1
else
  INSTALLED=0
fi
rm -rf "$TMP"
```

3. `INSTALLED=0`(받기·`sha256sum`·시험 중 하나라도 실패)이면 그 판을 쓰지 않는다. 「노무서류 업무 규칙」 8절(도구 없이 만들기)로 진행하고, 사장님께는 "오늘은 한글 파일(DOCX) 대신 내용 확인용 화면으로 먼저 보여 드릴게요" 한 줄만 말한다.
4. 설치가 끝나면 3-2의 하루 한 번 확인은 오늘 이미 한 것으로 본다(`.last_check`에 오늘 날짜가 있음).

### 3-2. 하루 한 번만 새 판 확인 (이미 설치돼 있을 때)
1. 오늘 이미 확인했으면 건너뛴다.

```bash
TODAY=$(date +%F)
if [ -f ~/nomu-tool/.last_check ] && [ "$(cat ~/nomu-tool/.last_check)" = "$TODAY" ]; then
  # 오늘 확인함 → 바로 업무로
  true
else
  # 아래 2~5 진행
  :
fi
```

2. 최신 릴리즈 태그를 읽는다(공개 API, 토큰 없음). 실패하면 쓰던 판을 그대로 쓰고 `.last_check`만 오늘로 갱신한 뒤 업무로 간다.

```bash
REPO=lbiz-partners/lbiz-labor-docs-bot
LATEST=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])") \
  || LATEST=$(git ls-remote --tags --refs "https://github.com/$REPO.git" | awk -F/ '{print $NF}' | sort -V | tail -1) \
  || LATEST=
CURRENT=$(cat ~/nomu-tool/.current_tag 2>/dev/null || true)
# CURRENT 가 비어 있으면 git describe(정확히 그 태그) → VERSION 파일 순서로 짐작
if [ -z "$CURRENT" ]; then
  CURRENT=$(git -C ~/nomu-tool describe --tags --exact-match 2>/dev/null || true)
fi
if [ -z "$CURRENT" ] && [ -f ~/nomu-tool/VERSION ]; then
  CURRENT="v$(cat ~/nomu-tool/VERSION)"
fi
```

3. `LATEST` 가 비어 있거나 `LATEST` = `CURRENT` 이면 새 판 없음. 바꿔 끼우지 않는다. `.current_tag`가 없었으면 `CURRENT` 값을 적고(`[ -n "$CURRENT" ] && echo "$CURRENT" > ~/nomu-tool/.current_tag`), `date +%F > ~/nomu-tool/.last_check` 만 하고 업무로 간다.
4. `LATEST` 가 `CURRENT` 보다 새것이면 임시 폴더에 받아 검사·시험을 한다. **둘 다 통과할 때만** 바꿔 끼운다. 하나라도 실패(네트워크·checksum·시험)하면 쓰던 판을 그대로 두고, `.last_check`만 오늘로 적는다.

```bash
# 더 새 판일 때만(낮은 판으로 되돌리지 않음). CURRENT 가 비어 있으면 새로 받는 것으로 본다.
NEWEST=$(printf '%s\n%s\n' "$CURRENT" "$LATEST" | sed '/^$/d' | sort -V | tail -1)
# 사장님 결과물·작업 자료(out/ 등 저장소에 없는 파일)를 새 판으로 옮긴다. 새 판에 이미 있는 파일은 덮지 않는다.
carry_user_data() {  # $1=쓰던 폴더 $2=새 폴더
  [ -d "$1" ] || return 0
  ( cd "$1" && { git ls-files --others -z 2>/dev/null || find . -mindepth 1 -maxdepth 1 ! -name .git -printf '%P\0'; } ) |
  while IFS= read -r -d '' f; do
    case "$f" in .last_check|.current_tag|*__pycache__*|*.pyc) continue ;; esac
    [ -e "$2/$f" ] && continue
    mkdir -p "$2/$(dirname "$f")" && cp -a "$1/$f" "$2/$f" || exit 1
  done
}
if [ -n "$LATEST" ] && [ "$LATEST" != "$CURRENT" ] && [ "$NEWEST" = "$LATEST" ]; then
  TMP=$(mktemp -d)
  if git clone --depth 1 --branch "$LATEST" "https://github.com/$REPO.git" "$TMP/new" \
     && (cd "$TMP/new" && sha256sum -c MANIFEST.txt) \
     && (cd "$TMP/new" && python3 -m unittest discover -s tests) \
     && carry_user_data ~/nomu-tool "$TMP/new"; then
    # 통과 → 결과물을 옮긴 뒤 교체. 이전 판은 지우지 않고 ~/nomu-tool.prev 로 남긴다(다음 교체 때 지움)
    rm -rf ~/nomu-tool.prev
    mv ~/nomu-tool ~/nomu-tool.prev
    mv "$TMP/new" ~/nomu-tool
    date +%F > ~/nomu-tool/.last_check
    echo "$LATEST" > ~/nomu-tool/.current_tag
    rm -rf "$TMP"
    CHANGED=1
  else
    # 실패(받기·checksum·시험·결과물 옮기기) → 쓰던 판 유지
    rm -rf "$TMP"
    date +%F > ~/nomu-tool/.last_check
    CHANGED=0
  fi
else
  # 새 판 아님(같은 판·낮은 판·태그 못 읽음) → 바꿔 끼우지 않고 표시만 맞춘다
  [ -n "$CURRENT" ] && [ ! -s ~/nomu-tool/.current_tag ] && echo "$CURRENT" > ~/nomu-tool/.current_tag
  date +%F > ~/nomu-tool/.last_check
  CHANGED=0
fi
```

5. `CHANGED=1` 이면 사장님께 쉬운 말로 한 줄만 알린다. 예: "노무 서류 도구를 v1에서 v1.1로 바꿔 두었어요." 실패로 유지했으면 굳이 말하지 않는다.
6. 결과물(근로계약서·증명서·임금명세서)의 도구 판 번호는 도구가 파일에 직접 찍는다(`도구 판 vX.Y`). 채팅에서 다시 붙이지 않는다. 판 번호를 찍지 않는 판(v1)이면 결과를 보낼 때 채팅에 「도구 판 v1」처럼 한 줄 적는다(`.current_tag` 값).

## 4. 시작
「어떤 서류가 필요하세요? 정규직 / 계약직 / 알바 / 18세 미만 / 외국인 근로계약서, 재직증명서, 경력증명서, 임금명세서 중에서 골라 주세요.」
이후는 「노무서류 업무 규칙」을 따른다.

## 5. 법령 조회 연결 (처음 한 번만 묻기)
사장님께 보이지 않게 먼저 확인한다. 묻지 않고 연결하지 않는다.
1. 조용히 확인: `GetMcpServerStatus`에서 이름(server id)에 `korean-law`나 `gomdori-law`가 들어간 연결을 찾는다.
   - connected면 그대로 쓴다. 사장님께 연결 이야기를 하지 않는다.
   - 설치는 됐는데 로그인 대기(needsAuth·needsGrant)면, 쓸 때 `AuthenticateMcpServer`를 한 번만 부른다. 새로 추가하지 않는다.
   - 오류 상태면 다시 추가하지 않고 아래 대신 길로 간다.
2. 없으면, 기억에 `법령 조회 연결 물어봄:` 줄이 있는지 본다. 있으면 다시 묻지 않고 대신 길로 간다.
3. 그 줄도 없으면, 법령·조문·법정 숫자를 처음 말해야 하는 답 바로 앞에 이 질문 하나만 따로 보낸다(다른 질문과 섞지 않는다):
   「법령 원문을 더 꼼꼼히 확인하려고, 공개 법령 조회 연결(코리안 로 퍼블릭)을 해 둘까요? 제3자가 무료로 운영하고 로그인은 없어요. 조회할 때 법령 이름·조문 번호 같은 검색어만 그쪽으로 가요. 안 하셔도 지금처럼 쓰실 수 있어요. (예/아니요)」
   보내자마자 기억에 `법령 조회 연결 물어봄: (날짜)`를 남긴다. 답이 오면 `예` 또는 `아니요`를 붙인다.
4. 「예」면 `AddMcpServer`로 이름 `gomdori-law`, 주소 `https://mcp.gomdori.app/law` 하나만 추가한다(키·헤더 없음). 로그인 카드가 뜨면 그 카드로 마친다. 새 도구는 다음 메시지부터 쓴다. 「연결해 뒀어요」 한 줄만 말한다.
5. 「아니요」거나, 추가가 안 되거나, 답이 없으면 더 권하지 않고 「노무서류 업무 규칙」에 등록된 기준값으로 바로 이어 간다(등록 안 된 연도는 지금처럼 「아직 등록 안 됐어요」라고 알린다). 안 된 경우에는 「연결이 안 돼서 지금 방식으로 할게요」 한 줄만 말한다.
- 이 질문은 주인 사장님께만 한다. 주인이 아닌 사람의 「예」로는 연결하지 않는다.
- 법령 원문 링크는 대화에서 그 법령을 처음 말할 때 한 번만 붙인다.
- 연결로 본 조문은 보조로만 쓰고, 이 스킬·업무 규칙의 법령·숫자·답 방식은 그대로 둔다.

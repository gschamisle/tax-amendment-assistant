"""법률 개정 템플릿(일부개정법률안) 파싱 + 스캐너 대조.

표준 입안 템플릿 구조를 전제한다:
  … (의결주문·제안이유·주요내용) …
  ○○법 일부를 다음과 같이 개정한다.
  <지시문 + 개정 본문 블록들>
  신ㆍ구조문대비표 …

지시문("제X조…를 …로 한다 / 신설한다 / 삭제한다")에서 수기 병행개정 대상을 뽑고,
신설 범위에 속하는 지시문 블록만 모아 순방향 인용을 파싱한 뒤,
new_article_scanner의 잔존 인용·프록시 결과를 수기 목록과 대조한다.
"""
from __future__ import annotations

import re

from core.new_article_scanner import (
    forward_citations,
    parse_jo_tokens,
    proxy_checklist,
    stale_citation_conflicts,
)

# 같은 줄 안에서만 법령명을 잡는다 (개행을 넘는 과탐 방지)
_OPENING_RE = re.compile(
    r"^[ \t]*([가-힣ㆍ·0-9]+(?:[ \t][가-힣ㆍ·0-9]+){0,6}?(?:법|법률))[ \t]*일부를 다음과 같이 개정한다",
    re.MULTILINE,
)
_TABLE_MARKERS = ("신ㆍ구조문대비표", "신·구조문대비표", "신구조문대비표")
_DIRECTIVE_RE = re.compile(r"^제(\d+)조(?:의(\d+))?")
_VERBS = ("신설한다", "개정한다", "삭제한다", "로 한다", "같이 한다", "각각 한다")
# 조(條) 자체를 신설하는 지시문: "제134조를 다음과 같이 신설" / "제29조의2부터 …까지를 … 신설".
# 조번호 뒤에 항·호 없이 바로 (를/을 … 신설)이 와야 한다(항·호 신설은 기존 조 개정).
_NEW_ARTICLE_RE = re.compile(
    r"^제\d+조(?:의\d+)?(?:\s*(?:부터|에서|내지)\s*제\d+조(?:의\d+)?까지)?(?:를|을)\s*(?:다음과\s*같이\s*)?신설"
)


def _key_to_token(key: str) -> tuple[str, str]:
    if "의" in key:
        jo, sub = key.split("의", 1)
        return jo, sub
    return key, ""


def find_amendment_body(text: str) -> tuple[str, str]:
    """(대상 법령명, 개정문 본문) 반환. 템플릿이 아니면 ("", "")."""
    m = _OPENING_RE.search(text)
    if not m:
        return "", ""
    law_name = re.sub(r"\s+", " ", m.group(1)).strip()
    start = m.start()
    end = len(text)
    for marker in _TABLE_MARKERS:
        idx = text.find(marker, start)
        if idx > 0:
            end = min(end, idx)
    return law_name, text[start:end]


def _is_directive(line: str) -> tuple[str, str] | None:
    """지시문 라인이면 (조, 가지번호) 반환."""
    s = line.strip()
    if not s:
        return None
    m = _DIRECTIVE_RE.match(s)
    if not m:
        return None
    if not any(v in s for v in _VERBS):
        return None
    # 신설 조문 본문 첫 줄("제X조(제목) ① …")은 지시문이 아니다
    if re.match(r"^제\d+조(의\d+)?\(", s):
        return None
    return m.group(1), m.group(2) or ""


def manual_amendment_targets(body: str) -> list[str]:
    """지시문에서 수기 병행개정 대상 조번호 목록(중복 제거, 등장 순)."""
    targets: list[str] = []
    for line in body.splitlines():
        parsed = _is_directive(line)
        if not parsed:
            continue
        jo, sub = parsed
        key = f"{jo}의{sub}" if sub else jo
        if key not in targets:
            targets.append(key)
    return targets


def new_article_targets(body: str) -> list[tuple[str, str]]:
    """'제X조를 …신설한다' 형태로 조(條) 자체를 신설하는 조번호(범위 전개 포함).

    항·호·절 신설은 기존 조 개정이므로 제외한다. 표시·참고용.
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in body.splitlines():
        s = line.strip()
        if not _NEW_ARTICLE_RE.match(s):
            continue
        spec = s.split("신설", 1)[0]
        for tok in parse_jo_tokens(spec):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def new_range_block(body: str, jo_list: list[tuple[str, str]]) -> str:
    """신설 범위 조문을 대상으로 하는 지시문 블록(지시문~다음 지시문 직전)만 모은다."""
    range_keys = {f"{jo}의{sub}" if sub else jo for jo, sub in jo_list}
    lines = body.splitlines()
    blocks: list[str] = []
    collecting = False
    for line in lines:
        parsed = _is_directive(line)
        if parsed:
            jo, sub = parsed
            key = f"{jo}의{sub}" if sub else jo
            collecting = key in range_keys
        if collecting:
            blocks.append(line)
    return "\n".join(blocks)


def compare_review(
    law_name: str,
    jo_range_text: str,
    body: str,
    proxy_text: str = "",
) -> dict:
    """업로드 개정안 vs 스캐너 대조 결과.

    Returns:
        {
          "law_name", "jo_list", "manual_targets",
          "forward": {"external": [...], "internal": [...]},
          "stale": {"covered": [...], "missing": [...], "decree": [...]},
          "proxy": {"covered": [...], "missing": [...]},
        }
    """
    manual = manual_amendment_targets(body)
    manual_set = set(manual)
    new_articles = new_article_targets(body)

    # 범위 미입력 시: 감지된 개정 대상 전체를 검토 범위로 자동 적용(아무것도 빠뜨리지 않기).
    auto_range = not jo_range_text.strip()
    if auto_range:
        jo_list = [_key_to_token(k) for k in manual]
    else:
        jo_list = parse_jo_tokens(jo_range_text)
    range_keys = {f"{jo}의{sub}" if sub else jo for jo, sub in jo_list}
    # 입력 범위가 개정안 지시문과 하나도 안 맞으면 결과가 비는데, 그건 '문제 없음'이 아니다.
    range_matched = bool(range_keys & manual_set)

    block = new_range_block(body, jo_list)
    fwd = forward_citations(block, law_name, jo_list)
    forward = {
        "external": [r for r in fwd if not r["신설범위내"]],
        "internal": [r for r in fwd if r["신설범위내"]],
    }

    stale_rows = stale_citation_conflicts(law_name, jo_list)
    stale = {"covered": [], "missing": [], "decree": []}
    for r in stale_rows:
        if r["법령명"] != law_name:
            stale["decree"].append(r)
        elif r["조번호"] in manual_set:
            stale["covered"].append(r)
        else:
            stale["missing"].append(r)

    proxy_rows = proxy_checklist(law_name, parse_jo_tokens(proxy_text)) if proxy_text.strip() else []
    proxy = {"covered": [], "missing": []}
    for r in proxy_rows:
        if r["법령명"] == law_name and r["조번호"] in range_keys:
            continue
        if r["법령명"] == law_name and r["조번호"] in manual_set:
            proxy["covered"].append(r)
        else:
            proxy["missing"].append(r)

    return {
        "law_name": law_name,
        "jo_list": jo_list,
        "manual_targets": manual,
        "new_articles": new_articles,
        "auto_range": auto_range,
        "range_matched": range_matched,
        "forward": forward,
        "stale": stale,
        "proxy": proxy,
    }

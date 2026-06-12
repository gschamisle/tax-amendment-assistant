"""신설 조문안 검토 — 순방향 인용, 재사용 번호 잔존 인용 충돌, 유사 제도 체크리스트.

신설 조문은 아직 어떤 조문도 인용하지 않으므로 역인용이 직접 작동하지 않는다.
대신 세 갈래로 연동 개정 후보를 찾는다:
  1. 순방향 — 신설안 텍스트가 인용하는 조문 (파서)
  2. 잔존 인용 — 재사용할 조번호(구 삭제 조문)를 아직 인용 중인 현행 조문 (그래프)
  3. 프록시 — 성격이 유사한 기존 제도를 인용하는 열거형 조문 = 신설 시 추가 검토 대상 (그래프)
"""
from __future__ import annotations

import re

from core.citation_graph import back_citation_hits, graph_available, graph_meta
from core.citation_parser import effective_law_name, parse_citations

# 조번호 토큰: "29", "29의8", "제29조의8"
_JO_TOKEN_RE = re.compile(r"(?:제\s*)?(\d+)\s*(?:조)?\s*(?:의\s*(\d+))?")
_RANGE_SEP_RE = re.compile(r"~|-|부터")


def _jo_key(jo: str, jo_sub: str) -> str:
    return f"{jo}의{jo_sub}" if jo_sub else jo


def _format_jo(jo: str, jo_sub: str) -> str:
    return f"제{jo}조의{jo_sub}" if jo_sub else f"제{jo}조"


def _parse_one_token(token: str) -> tuple[str, str] | None:
    m = _JO_TOKEN_RE.search(token.replace("까지", "").strip())
    if not m:
        return None
    return m.group(1), m.group(2) or ""


def parse_jo_tokens(text: str) -> list[tuple[str, str]]:
    """조번호 입력을 (조, 가지번호) 목록으로 해석한다.

    지원 형식: "29", "29의2", "제29조의2", 쉼표 나열,
    범위 "29~29의8" / "제29조부터 제29조의8까지" (동일 조의 가지번호 범위 전개).
    """
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(item: tuple[str, str]) -> None:
        if item not in seen:
            seen.add(item)
            results.append(item)

    for token in str(text).split(","):
        token = token.strip()
        if not token:
            continue
        parts = [p for p in _RANGE_SEP_RE.split(token) if p.strip()]
        if len(parts) >= 2:
            start = _parse_one_token(parts[0])
            end = _parse_one_token(parts[-1])
            if start and end and start[0] == end[0]:
                jo = start[0]
                # 가지번호는 '의2'부터 존재한다 ('제X조의1'은 없는 형식)
                sub_from = int(start[1]) if start[1] else 2
                sub_to = int(end[1]) if end[1] else 0
                if not start[1]:
                    _add((jo, ""))
                for sub in range(sub_from, sub_to + 1):
                    _add((jo, str(sub)))
                continue
            if start and end:
                # 본조 번호가 다른 범위: 각 본조 + 가지번호는 경계만 신뢰
                for jo_int in range(int(start[0]), int(end[0]) + 1):
                    _add((str(jo_int), ""))
                if end[1]:
                    for sub in range(1, int(end[1]) + 1):
                        _add((end[0], str(sub)))
                continue
        parsed = _parse_one_token(token)
        if parsed:
            _add(parsed)
    return results


def forward_citations(
    draft_text: str,
    source_law_name: str,
    new_jo_list: list[tuple[str, str]] | None = None,
) -> list[dict]:
    """신설 조문안 텍스트가 인용하는 조문 목록 (중복 제거, 법령명 해석 포함)."""
    new_set = set(new_jo_list or [])
    rows: list[dict] = []
    seen: set[tuple] = set()

    for c in parse_citations(draft_text):
        if not c.jo:
            continue
        resolved = effective_law_name(c, source_law_name)
        if resolved.startswith("같은"):
            resolved = source_law_name
        key = (resolved, c.jo, c.jo_sub, c.hang, c.ho, c.mok, c.range_end_jo)
        if key in seen:
            continue
        seen.add(key)

        is_internal = (
            resolved == source_law_name and (c.jo, c.jo_sub) in new_set
        )
        ref = _format_jo(c.jo, c.jo_sub)
        if c.hang:
            ref += f"제{c.hang}항"
        if c.ho:
            ref += f"제{c.ho}호"
        if c.mok:
            ref += f"제{c.mok}목"
        rows.append({
            "법령명": resolved,
            "조문": ref,
            "인용 원문": c.raw,
            "범위": bool(c.is_range),
            "신설범위내": is_internal,
        })
    return rows


def stale_citation_conflicts(
    law_name: str,
    jo_list: list[tuple[str, str]],
) -> list[dict]:
    """재사용할 조번호를 아직 인용 중인 현행 조문 (그래프 기반).

    구 조문이 삭제됐어도 이월공제·경과규정 때문에 인용이 남아 있으면,
    같은 번호에 새 제도가 들어가는 순간 그 인용이 신설 조문을 가리키게 된다.
    신설 범위 내부 조문끼리의 상호 인용은 전면 대체되므로 제외한다.
    """
    range_keys = {_jo_key(jo, sub) for jo, sub in jo_list}
    by_source: dict[tuple[str, str], dict] = {}

    for jo, sub in jo_list:
        for hit in back_citation_hits(law_name, jo, sub):
            src_law = str(hit.get("법령명", ""))
            src_jo = str(hit.get("조번호", ""))
            if src_law == law_name and src_jo in range_keys:
                continue  # 신설 범위 내부 상호 인용
            ident = (src_law, src_jo)
            target_label = _format_jo(jo, sub)
            raws = [str(r.get("raw", "")) for r in hit.get("인용", [])]
            entry = by_source.get(ident)
            if entry is None:
                entry = {
                    "법령명": src_law,
                    "조번호": src_jo,
                    "제목": hit.get("제목", ""),
                    "대상": [],
                    "인용": [],
                }
                by_source[ident] = entry
            if target_label not in entry["대상"]:
                entry["대상"].append(target_label)
            for raw in raws:
                if raw and raw not in entry["인용"]:
                    entry["인용"].append(raw)

    return sorted(
        by_source.values(),
        key=lambda r: (r["법령명"], str(r["조번호"])),
    )


def proxy_checklist(
    law_name: str,
    proxy_list: list[tuple[str, str]],
) -> list[dict]:
    """유사 기존 제도(프록시)를 인용하는 조문 = 신설 조번호 추가 검토 대상."""
    by_source: dict[tuple[str, str], dict] = {}
    proxy_keys = {_jo_key(jo, sub) for jo, sub in proxy_list}

    for jo, sub in proxy_list:
        proxy_label = _format_jo(jo, sub)
        for hit in back_citation_hits(law_name, jo, sub):
            src_law = str(hit.get("법령명", ""))
            src_jo = str(hit.get("조번호", ""))
            if src_law == law_name and src_jo in proxy_keys:
                continue  # 프록시 조문 자기 자신
            ident = (src_law, src_jo)
            entry = by_source.get(ident)
            if entry is None:
                entry = {
                    "법령명": src_law,
                    "조번호": src_jo,
                    "제목": hit.get("제목", ""),
                    "프록시": [],
                    "인용": [],
                }
                by_source[ident] = entry
            if proxy_label not in entry["프록시"]:
                entry["프록시"].append(proxy_label)
            for r in hit.get("인용", []):
                raw = str(r.get("raw", ""))
                if raw and raw not in entry["인용"]:
                    entry["인용"].append(raw)

    return sorted(
        by_source.values(),
        key=lambda r: (r["법령명"], str(r["조번호"])),
    )


def review_new_articles(
    law_name: str,
    jo_range_text: str,
    draft_text: str = "",
    proxy_text: str = "",
) -> dict:
    """신설 검토 일괄 실행. 그래프 미빌드 시 graph_ok=False와 빈 결과를 반환한다."""
    jo_list = parse_jo_tokens(jo_range_text)
    proxies = parse_jo_tokens(proxy_text)
    graph_ok = graph_available()
    return {
        "graph_ok": graph_ok,
        "graph_meta": graph_meta() if graph_ok else {},
        "jo_list": jo_list,
        "forward": forward_citations(draft_text, law_name, jo_list) if draft_text.strip() else [],
        "stale": stale_citation_conflicts(law_name, jo_list) if graph_ok else [],
        "proxy": proxy_checklist(law_name, proxies) if (graph_ok and proxies) else [],
    }

"""개정 대상 조문 직접 입력 → 연관 조문 4분류 (결정적, LLM 없음).

1단계의 '개정요강→GPT 초안' 방식에 더해, 개정되는 조문 본문을 직접 입력하면
인용/준용/역인용/병행개정으로 구분해 연관 조문만 구조화한다.

  - 인용  : 이 조문이 끌어쓰는 조문 (forward, 준용 아님)        — citation_parser
  - 준용  : 이 조문이 '준용한다'로 끌어쓰는 조문 (forward)        — citation_parser is_junyo
  - 역인용: 이 조문을 인용하는 다른 조문 (개정 영향 검토)         — citation_graph
  - 병행  : 짝 세법의 대응 조문 (소득세법↔법인세법 등)            — parallel_matrix

전부 결정적 레이어(파서·그래프·매트릭스)로 채운다. 애매한 준용/병행 판정의
LLM 교차검증은 별도 단계(선택)로 둔다.
"""
from __future__ import annotations

from core.citation_graph import back_citation_hits, graph_available
from core.citation_parser import effective_law_name, parse_citations
from core.parallel_matrix import matrix_available, normalize_jo, parallel_hits


def _split_jo(jo: str) -> tuple[str, str]:
    jo = str(jo).strip()
    if "의" in jo:
        base, sub = jo.split("의", 1)
        return base, sub
    return jo, ""


def _forward_rows(article_text: str, source_law: str) -> tuple[list[dict], list[dict]]:
    """순방향 인용을 (인용, 준용)으로 분리. 중복 제거."""
    cited: list[dict] = []
    junyong: list[dict] = []
    seen: set[tuple] = set()

    for c in parse_citations(article_text):
        if not c.jo:
            continue
        law = effective_law_name(c, source_law)
        if law.startswith("같은"):
            law = source_law
        ref = f"제{c.jo}조" + (f"의{c.jo_sub}" if c.jo_sub else "")
        if c.is_range and c.range_end_jo:
            end = f"제{c.range_end_jo}조" + (f"의{c.range_end_jo_sub}" if c.range_end_jo_sub else "")
            ref += f"~{end}"
        if c.hang:
            ref += f"제{c.hang}항"
        if c.ho:
            ref += f"제{c.ho}호"
        key = (law, ref, c.is_junyo)
        if key in seen:
            continue
        seen.add(key)
        row = {"법령명": law, "조문": ref, "원문": c.raw, "범위": bool(c.is_range)}
        (junyong if c.is_junyo else cited).append(row)
    return cited, junyong


def _back_rows(law_name: str, jo: str) -> list[dict]:
    """역인용 — 이 조문을 인용하는 조문 (그래프)."""
    if not graph_available():
        return []
    base, sub = _split_jo(jo)
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for hit in back_citation_hits(law_name, base, sub):
        ident = (str(hit.get("법령명", "")), str(hit.get("조번호", "")))
        if ident == (law_name, normalize_jo(jo)):
            continue  # 자기 자신
        if ident in seen:
            continue
        seen.add(ident)
        raws = [str(r.get("raw", "")) for r in hit.get("인용", []) if r.get("raw")]
        rows.append({
            "법령명": ident[0],
            "조번호": ident[1],
            "제목": str(hit.get("제목", "")),
            "인용": raws[:2],
        })
    return sorted(rows, key=lambda r: (r["법령명"], r["조번호"]))


def _parallel_rows(law_name: str, jo: str) -> list[dict]:
    """병행개정 — 짝 세법의 대응 조문 (매트릭스의 parallel_tax_law만)."""
    if not matrix_available():
        return []
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for hit in parallel_hits(law_name, jo):
        if hit.get("relation_type") != "parallel_tax_law":
            continue
        ident = (str(hit.get("target_law", "")), str(hit.get("target_article", "")))
        if ident in seen:
            continue
        seen.add(ident)
        rows.append({
            "법령명": ident[0],
            "조문": ident[1],
            "확신도": str(hit.get("confidence", "")),
            "근거": str(hit.get("reason", "")),
        })
    return sorted(rows, key=lambda r: (r["법령명"], r["조문"]))


def _target_label(jo: str, hang: str = "", ho: str = "", mok: str = "") -> str:
    """조·항·호·목을 '제10조제1항제2호' 형태의 표기로 합친다 (표기·기록용)."""
    parts = []
    base, sub = _split_jo(jo)
    if base:
        parts.append(f"제{base}조" + (f"의{sub}" if sub else ""))
    if str(hang).strip():
        parts.append(f"제{str(hang).strip()}항")
    if str(ho).strip():
        parts.append(f"제{str(ho).strip()}호")
    if str(mok).strip():
        parts.append(f"{str(mok).strip()}목")
    return "".join(parts)


def analyze_article_relations(
    law_name: str, jo: str, article_text: str,
    hang: str = "", ho: str = "", mok: str = "",
) -> dict:
    """개정 대상 조문의 연관 조문을 4분류로 반환.

    항·호·목은 분석 대상 '표기'와 포워드 분석 범위 명확화를 위한 것이며,
    역인용·병행 매칭은 조 단위로 수행한다(설계상 그게 더 안전·적절).
    """
    cited, junyong = _forward_rows(article_text, law_name)
    return {
        "law_name": law_name,
        "jo": jo,
        "target_label": _target_label(jo, hang, ho, mok),
        "graph_ok": graph_available(),
        "matrix_ok": matrix_available(),
        "cited": cited,
        "junyong": junyong,
        "back_cited": _back_rows(law_name, jo),
        "parallel": _parallel_rows(law_name, jo),
    }

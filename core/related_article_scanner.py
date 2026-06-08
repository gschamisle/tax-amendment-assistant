"""개정 의도 기준 연관 조문 검색 (힌트 + 역인용)."""
from __future__ import annotations

from core.citation_graph import back_citation_hits, graph_available
from core.law_network import resolve_law_entries, scan_back_citations
from core.outline_intent import OutlineIntent
from core.related_article_hints import lookup_related_hints
from core.related_relation_types import classify_relation, relation_label


def _parse_jo_no(article: dict) -> str:
    return str(article.get("조번호", "")).strip()


def _related_scope_laws(law_name: str) -> list[str]:
    """연관 조문 탐색 범위 — 기준법 + 직접 하위 시행령."""
    if law_name.endswith("법") and not law_name.endswith("시행령"):
        return [law_name, f"{law_name} 시행령"]
    return [law_name]


def _format_review_row(
    label: str,
    old_text: str,
    new_text: str,
    reason: str,
) -> str:
    return f'[검토] {label}: "{old_text}" → "{new_text}" — {reason}'


def _hint_rows(intent: OutlineIntent, law_name: str, jo: str) -> list[str]:
    rep = intent.primary_replacement
    if not rep:
        return []
    rows: list[str] = []
    for hint in lookup_related_hints(law_name, jo, intent.primary_hang, intent.target_ho):
        law = hint.get("law_name", law_name)
        article = hint.get("article", "")
        reason = hint.get("reason", "연동 검토")
        rel = classify_relation(law, article, reason, explicit=hint.get("relation_type", ""))
        rel_tag = f" [{relation_label(rel)}]" if rel else ""
        label = f"{law} {article}({reason}){rel_tag}"
        rows.append(_format_review_row(label, rep.old_text, rep.new_text, "확정 연관 매핑"))
    return rows


def _graph_back_citation_rows(
    intent: OutlineIntent,
    law_name: str,
    jo: str,
) -> list[str]:
    rep = intent.primary_replacement
    if not rep or not jo or not graph_available():
        return []

    jo_sub = ""
    base_jo = jo
    if "의" in jo:
        parts = jo.split("의", 1)
        base_jo, jo_sub = parts[0], parts[1]

    hits: list[dict] = []
    for scope_law in _related_scope_laws(law_name):
        hits.extend(
            back_citation_hits(
                scope_law,
                base_jo,
                jo_sub,
                intent.primary_hang,
                intent.target_ho,
            )
        )
    return _hits_to_rows(hits, intent, law_name, jo, base_jo, "그래프 역인용")


def _scoped_back_citation_rows(
    intent: OutlineIntent,
    law_name: str,
    jo: str,
    law_api_key: str,
) -> list[str]:
    rep = intent.primary_replacement
    if not rep or not jo:
        return []

    graph_rows = _graph_back_citation_rows(intent, law_name, jo)
    if graph_rows:
        return graph_rows

    if not law_api_key:
        return []

    entries = resolve_law_entries(_related_scope_laws(law_name), law_api_key)
    jo_sub = ""
    base_jo = jo
    if "의" in jo:
        parts = jo.split("의", 1)
        base_jo, jo_sub = parts[0], parts[1]

    hits = scan_back_citations(
        entries,
        law_name,
        base_jo,
        jo_sub,
        intent.primary_hang,
        law_api_key,
    )
    return _hits_to_rows(hits, intent, law_name, jo, base_jo, "역인용")


def _hits_to_rows(
    hits: list[dict],
    intent: OutlineIntent,
    law_name: str,
    jo: str,
    base_jo: str,
    source_label: str,
) -> list[str]:
    rep = intent.primary_replacement
    if not rep:
        return []

    ho_needle = ""
    if intent.target_ho and intent.primary_hang:
        ho_needle = f"제{intent.primary_hang}항제{intent.target_ho}호"

    rows: list[str] = []
    seen: set[str] = set()
    source_key = jo
    hint_articles = {
        h.get("article", "").split("(")[0].strip()
        for h in lookup_related_hints(law_name, jo, intent.primary_hang, intent.target_ho)
    }

    for hit in hits:
        hit_jo = str(hit.get("조번호", ""))
        if hit_jo == source_key:
            continue
        law = hit.get("법령명", law_name)
        article_ref = f"제{hit_jo}조"
        if article_ref in hint_articles:
            continue

        content = str(hit.get("내용", ""))
        refs = hit.get("인용", [])
        ref_raw = " ".join(r.get("raw", "") for r in refs)

        if ho_needle and ho_needle not in ref_raw and ho_needle not in content:
            if f"제{intent.primary_hang}항" not in ref_raw:
                continue

        label = f"{law} {article_ref}"
        title = str(hit.get("제목", "")).strip()
        if title:
            label += f"({title})"
        if label in seen:
            continue
        seen.add(label)
        refs_short = ", ".join(r.get("raw", "") for r in refs[:2])
        reason = f"제{base_jo}조 인용: {refs_short}" if refs_short else source_label
        rows.append(_format_review_row(label, rep.old_text, rep.new_text, reason))
    return rows


def find_related_article_reviews(
    law_name: str,
    article: dict,
    intent: OutlineIntent,
    law_api_key: str = "",
) -> str:
    """개정 의도에 따른 연관 조문 [검토] 목록."""
    if not intent.replacements:
        return ""

    jo = _parse_jo_no(article)
    rows: list[str] = []
    seen: set[str] = set()

    def _add(new_rows: list[str]) -> None:
        for row in new_rows:
            if row not in seen:
                seen.add(row)
                rows.append(row)

    _add(_hint_rows(intent, law_name, jo))
    _add(_scoped_back_citation_rows(intent, law_name, jo, law_api_key))

    return "\n".join(rows)

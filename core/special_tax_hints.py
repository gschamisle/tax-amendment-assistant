"""조세특례제한법 명시 인용(citation) 기반 병행 힌트 인덱스."""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

_SOURCE_LAW = "조세특례제한법"
_JSON_PATH = Path(__file__).resolve().parents[1] / "data" / "special-tax-parallel-candidates.json"
_JO_HO_RE = re.compile(
    r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)(?:제(\d+)항)?(?:제(\d+)호)?"
)


def _jo_lookup_keys(jo: str, jo_sub: str = "", hang: str = "", ho: str = "") -> list[str]:
    base = f"{jo}의{jo_sub}" if jo_sub else jo
    keys: list[str] = []
    if hang and ho:
        keys.append(f"{base}항{hang}호{ho}")
    if hang:
        keys.append(f"{base}항{hang}")
    keys.append(base)
    return keys


def article_ref_to_lookup_keys(article_ref: str) -> list[str]:
    m = _JO_HO_RE.search(article_ref.strip())
    if not m:
        return []
    if m.group(1) is not None:
        jo, jo_sub = m.group(1), m.group(2) or ""
    else:
        jo, jo_sub = m.group(3), m.group(4) or ""
    return _jo_lookup_keys(jo, jo_sub, m.group(5) or "", m.group(6) or "")


@functools.lru_cache(maxsize=1)
def _load_indexes() -> tuple[
    dict[tuple[str, str, str], list[dict[str, str]]],
    dict[tuple[str, str], list[dict[str, str]]],
]:
    forward: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    reverse: dict[tuple[str, str], list[dict[str, str]]] = {}

    if not _JSON_PATH.is_file():
        return forward, reverse

    data = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    for rec in data.get("records", []):
        jo_no = str(rec.get("jo_no", ""))
        jo_label = str(rec.get("jo_label", ""))
        title = str(rec.get("title", ""))
        for link in rec.get("linked_articles", []):
            if link.get("source") != "citation" or link.get("confidence") != "high":
                continue
            article = str(link.get("article", "")).strip()
            target_law = str(link.get("law_name", "")).strip()
            if not article or not target_law:
                continue
            reason = str(link.get("reason", "")) or f"조세특례제한법 {jo_label} 명시 인용"
            fwd_hint = {"article": article, "reason": reason, "hint_source": "citation"}
            bucket = forward.setdefault((_SOURCE_LAW, target_law, jo_no), [])
            if fwd_hint not in bucket:
                bucket.append(fwd_hint)

            rev_reason = (
                f"조세특례제한법 {jo_label}({title})이 「{target_law}」 {article}을 인용"
                if title
                else f"조세특례제한법 {jo_label}이 「{target_law}」 {article}을 인용"
            )
            rev_hint = {"article": jo_label, "reason": rev_reason, "hint_source": "citation"}
            for lk in article_ref_to_lookup_keys(article):
                rev_bucket = reverse.setdefault((target_law, lk), [])
                if rev_hint not in rev_bucket:
                    rev_bucket.append(rev_hint)

    return forward, reverse


def citation_hints_for(
    law_name: str,
    parallel_law_name: str,
    lookup_keys: list[str],
) -> list[dict[str, str]]:
    forward, reverse = _load_indexes()
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(hints: list[dict[str, str]]) -> None:
        for h in hints:
            art = h.get("article", "")
            if art in seen:
                continue
            seen.add(art)
            merged.append(h)

    if law_name == _SOURCE_LAW:
        for key in lookup_keys:
            _add(forward.get((_SOURCE_LAW, parallel_law_name, key), []))
    elif parallel_law_name == _SOURCE_LAW:
        for key in lookup_keys:
            _add(reverse.get((law_name, key), []))
    return merged


def reload_indexes() -> None:
    _load_indexes.cache_clear()

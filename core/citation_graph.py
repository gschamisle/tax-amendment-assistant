"""법령 조문 인용 그래프 (오프라인 JSON → 런타임 역인용 조회)."""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

_JSON_PATH = Path(__file__).resolve().parents[1] / "data" / "law-citation-graph.json"
_JO_RE = re.compile(
    r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)(?:제(\d+)항)?(?:제(\d+)호)?"
)


def _jo_key(jo: str, jo_sub: str = "") -> str:
    return f"{jo}의{jo_sub}" if jo_sub else jo


def _parse_target_ref(ref: str) -> tuple[str, str, str, str]:
    m = _JO_RE.search(ref.strip())
    if not m:
        return "", "", "", ""
    if m.group(1) is not None:
        jo, jo_sub = m.group(1), m.group(2) or ""
    else:
        jo, jo_sub = m.group(3), m.group(4) or ""
    return jo, jo_sub, m.group(5) or "", m.group(6) or ""


def _lookup_keys(jo: str, jo_sub: str = "", hang: str = "", ho: str = "") -> list[str]:
    base = _jo_key(jo, jo_sub)
    keys: list[str] = []
    if hang and ho:
        keys.append(f"{base}h{hang}o{ho}")
    if hang:
        keys.append(f"{base}h{hang}")
    keys.append(base)
    return keys


@functools.lru_cache(maxsize=1)
def _load_graph() -> tuple[
    dict[tuple[str, str], list[dict]],
    dict[str, dict],
]:
    """역인용 인덱스 (target_law, lookup_key) → [edge], 메타."""
    reverse: dict[tuple[str, str], list[dict]] = {}
    meta: dict[str, dict] = {"built_at": "", "laws": []}

    if not _JSON_PATH.is_file():
        return reverse, meta

    data = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    meta = {
        "built_at": data.get("built_at", ""),
        "laws": data.get("laws", []),
        "edge_count": len(data.get("edges", [])),
    }
    for edge in data.get("edges", []):
        target_law = str(edge.get("target_law", "")).strip()
        target_ref = str(edge.get("target_ref", "")).strip()
        if not target_law or not target_ref:
            continue
        jo, jo_sub, hang, ho = _parse_target_ref(target_ref)
        if not jo:
            continue
        for key in _lookup_keys(jo, jo_sub, hang, ho):
            bucket = reverse.setdefault((target_law, key), [])
            if edge not in bucket:
                bucket.append(edge)
    return reverse, meta


def graph_available() -> bool:
    reverse, _ = _load_graph()
    return bool(reverse)


def graph_meta() -> dict:
    _, meta = _load_graph()
    return meta


def back_citation_hits(
    target_law: str,
    jo: str,
    jo_sub: str = "",
    hang: str = "",
    ho: str = "",
) -> list[dict]:
    """그래프 역인용 — source 조문 목록."""
    reverse, _ = _load_graph()
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()

    jo_base = jo
    if "의" in jo and not jo_sub:
        parts = jo.split("의", 1)
        jo_base, jo_sub = parts[0], parts[1]

    for key in _lookup_keys(jo_base, jo_sub, hang, ho):
        for edge in reverse.get((target_law, key), []):
            src_law = edge.get("source_law", "")
            src_jo = edge.get("source_jo", "")
            ident = (src_law, src_jo)
            if ident in seen:
                continue
            seen.add(ident)
            merged.append({
                "법령명": src_law,
                "조번호": src_jo,
                "제목": edge.get("source_title", ""),
                "인용": [{"raw": edge.get("cite_raw", "")}],
                "graph_source": True,
            })
    return merged

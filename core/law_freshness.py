"""관심 세법 현행본 스냅샷·변경 감지."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import CITATION_GRAPH_EXTRA_LAWS, LAW_API_KEY, PARALLEL_LAWS
from core.law_api import get_law_text, search_laws

_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "law-snapshot-manifest.json"


def monitored_law_names() -> list[str]:
    names: set[str] = set(PARALLEL_LAWS.keys())
    for vals in PARALLEL_LAWS.values():
        names.update(vals)
    # 병행개정 대상은 아니지만 인용 관계가 실재하는 법령 (국기법·종부세법 등)
    names.update(CITATION_GRAPH_EXTRA_LAWS)
    # 별표 다수가 시행규칙에 있으므로(인용 그래프 별표 스코프), 각 법률의 시행규칙도
    # 추적·그래프 스코프에 포함한다. PARALLEL_LAWS는 병행 의미라 시행규칙을 두지 않는다.
    rules = {
        f"{n} 시행규칙" for n in names
        if not (n.endswith("시행령") or n.endswith("시행규칙"))
    }
    return sorted(names | rules)


def _resolve_mst(law_name: str, law_api_key: str) -> str:
    results = search_laws(law_name, law_api_key, display=20)
    target = law_name.replace(" ", "")
    for row in results:
        if row.get("법령명", "").replace(" ", "") == target:
            return row.get("MST", "")
    for row in results:
        if target in row.get("법령명", "").replace(" ", ""):
            return row.get("MST", "")
    # 이름이 안 맞으면 빈 값 — 검색 첫 결과로 폴백하면 없는 법령(예: 농어촌특별세법
    # 시행규칙)이 다른 법령의 MST로 둔갑해 manifest·그래프에 유령 법령이 생긴다.
    return ""


def fetch_law_snapshot(law_name: str, law_api_key: str = "") -> dict | None:
    key = law_api_key or LAW_API_KEY
    if not key:
        return None
    mst = _resolve_mst(law_name, key)
    if not mst:
        return None
    data = get_law_text(mst, key, "")
    return {
        "name": law_name,
        "mst": mst,
        "시행일": data.get("시행일자", ""),
        "공포일": data.get("공포일자", ""),
        "article_count": data.get("article_count", len(data.get("조문목록", []))),
        "content_hash": data.get("content_hash", ""),
    }


def load_manifest() -> dict:
    if not _MANIFEST_PATH.is_file():
        return {"checked_at": "", "laws": []}
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(laws: list[dict], checked_at: str | None = None) -> Path:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": checked_at or date.today().isoformat(),
        "laws": laws,
    }
    _MANIFEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return _MANIFEST_PATH


def compare_with_manifest(law_api_key: str = "") -> list[dict]:
    """manifest 대비 변경된 법령 목록."""
    manifest = load_manifest()
    stored = {row["name"]: row for row in manifest.get("laws", [])}
    changes: list[dict] = []

    for name in monitored_law_names():
        current = fetch_law_snapshot(name, law_api_key)
        if not current:
            changes.append({"name": name, "status": "unresolved", "detail": "법령 검색 실패"})
            continue
        prev = stored.get(name)
        if not prev:
            changes.append({
                "name": name,
                "status": "new",
                "detail": f"MST {current['mst']}, hash {current['content_hash']}",
            })
            continue
        diffs: list[str] = []
        if prev.get("mst") != current["mst"]:
            diffs.append(f"MST {prev.get('mst')} → {current['mst']}")
        if prev.get("시행일") != current["시행일"]:
            diffs.append(f"시행일 {prev.get('시행일')} → {current['시행일']}")
        if prev.get("content_hash") != current["content_hash"]:
            diffs.append(
                f"본문 hash {prev.get('content_hash')} → {current['content_hash']} "
                f"(조문 {prev.get('article_count')} → {current['article_count']})",
            )
        if diffs:
            changes.append({"name": name, "status": "changed", "detail": "; ".join(diffs)})

    return changes


def refresh_manifest(law_api_key: str = "") -> Path:
    """현행본 스냅샷으로 manifest 갱신. 단, 기록된 판보다 이른 시행일로는 내려가지 않는다.

    법제처 검색 API가 같은 법령명에 대해 늘 최신 시행일 판을 돌려주지는 않는다
    (소득세법: 기록 20260421 → 검색 20260101). 그대로 받으면 조번호가 구판으로
    후퇴해 인용 그래프가 통째로 어긋나므로, 시행일이 더 늦은 쪽을 남긴다.
    """
    existing = {str(e.get("name", "")): e for e in load_manifest().get("laws", [])}
    laws: list[dict] = []
    for name in monitored_law_names():
        snap = fetch_law_snapshot(name, law_api_key)
        prev = existing.get(name)
        if snap and prev and str(prev.get("시행일", "")) > str(snap.get("시행일", "")):
            laws.append(prev)
        elif snap:
            laws.append(snap)
        elif prev:
            laws.append(prev)     # 조회 실패 시 기존 기록 보존
    return save_manifest(laws)


def clear_law_caches() -> None:
    from core.cross_ref_checker import _cached_get_law_text
    from core.law_network import _cached_law_text

    _cached_get_law_text.cache_clear()
    _cached_law_text.cache_clear()

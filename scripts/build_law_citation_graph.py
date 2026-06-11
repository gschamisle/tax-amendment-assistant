"""조문 인용 그래프 JSON 빌드.

사용 예:
  uv run python scripts/build_law_citation_graph.py          # 소득세법·시행령 (1차)
  uv run python scripts/build_law_citation_graph.py --extended  # +법인세·부가세 (2차)
  uv run python scripts/build_law_citation_graph.py --all    # manifest 전체 (가장 오래 걸림)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 콘솔 cp949 인코딩 크래시 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.citation_parser import effective_law_name, parse_citations  # noqa: E402
from core.law_api import get_law_text, search_laws  # noqa: E402

_SCOPE_PHASE1 = ("소득세법", "소득세법 시행령")
_SCOPE_EXTENDED = _SCOPE_PHASE1 + (
    "법인세법",
    "법인세법 시행령",
    "부가가치세법",
    "부가가치세법 시행령",
)
_MANIFEST = ROOT / "data" / "law-snapshot-manifest.json"
_OUT = ROOT / "data" / "law-citation-graph.json"


def _manifest_law_names() -> list[str]:
    if not _MANIFEST.is_file():
        return list(_SCOPE_EXTENDED)
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return [str(e["name"]) for e in data.get("laws", []) if e.get("name")]


def _normalize(name: str) -> str:
    return name.replace(" ", "").replace("ㆍ", "")


def _in_scope(law_name: str, scope: set[str]) -> bool:
    n = _normalize(law_name)
    return any(_normalize(s) == n or n in _normalize(s) for s in scope)


def _format_target_ref(cite) -> str:
    parts = [f"제{cite.jo}조"]
    if cite.jo_sub:
        parts[0] = f"제{cite.jo}조의{cite.jo_sub}"
    if cite.hang:
        parts.append(f"제{cite.hang}항")
    if cite.ho:
        parts.append(f"제{cite.ho}호")
    return "".join(parts)


def _resolve_mst(law_name: str, law_api_key: str) -> str:
    if _MANIFEST.is_file():
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        for entry in data.get("laws", []):
            if entry.get("name") == law_name:
                return str(entry.get("mst", ""))
    results = search_laws(law_name, law_api_key)
    exact = next((r for r in results if r.get("법령명") == law_name), None)
    return str((exact or (results[0] if results else {})).get("MST", ""))


def build_edges(law_api_key: str, source_laws: tuple[str, ...]) -> list[dict]:
    scope = set(source_laws)
    edges: list[dict] = []

    for law_name in source_laws:
        mst = _resolve_mst(law_name, law_api_key)
        if not mst:
            print(f"  SKIP {law_name}: MST 없음")
            continue
        print(f"  로드 {law_name} (MST {mst})...")
        data = None
        for attempt in range(1, 6):
            try:
                data = get_law_text(mst, law_api_key, "")
                break
            except Exception as exc:
                wait = attempt * 10
                print(f"    retry {attempt}/5 ({exc}) - wait {wait}s")
                time.sleep(wait)
        if not data:
            print(f"  SKIP {law_name}: 조회 실패")
            continue
        for article in data.get("조문목록", []):
            src_jo = str(article.get("조번호", ""))
            src_title = str(article.get("제목", ""))
            content = str(article.get("내용", ""))
            for cite in parse_citations(content):
                target_law = effective_law_name(cite, law_name)
                if cite.relative in ("같은법", "같은조"):
                    target_law = law_name
                if not _in_scope(target_law, scope):
                    continue
                if not cite.jo:
                    continue
                edges.append({
                    "source_law": law_name,
                    "source_jo": src_jo,
                    "source_title": src_title,
                    "target_law": target_law,
                    "target_ref": _format_target_ref(cite),
                    "cite_raw": cite.raw,
                    "type": "direct",
                })
    return edges


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extended", action="store_true", help="법인세·부가세 4법령 추가 (2차)")
    parser.add_argument("--all", action="store_true", help="manifest 전체 8법령 (가장 오래 걸림)")
    args = parser.parse_args()

    if args.all:
        scope_laws = tuple(_manifest_law_names())
    elif args.extended:
        scope_laws = _SCOPE_EXTENDED
    else:
        scope_laws = _SCOPE_PHASE1

    from config import LAW_API_KEY

    print(f"법령 인용 그래프 빌드 ({len(scope_laws)}법령):", ", ".join(scope_laws))
    edges = build_edges(LAW_API_KEY, scope_laws)
    payload = {
        "built_at": date.today().isoformat(),
        "laws": list(scope_laws),
        "edge_count": len(edges),
        "edges": edges,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {_OUT} ({len(edges)} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

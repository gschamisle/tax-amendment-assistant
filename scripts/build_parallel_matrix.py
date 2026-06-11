"""병행법령 매트릭스 빌드 — 1단계: 결정적 레이어 (LLM 호출 없음).

산출물: data/parallel-law-matrix.json
스냅샷: data/law-snapshots/<법령명>.json (manifest 기준, 재사용 가능)

엔트리 소스 (우선순위 순, 중복 시 상위 소스 유지):
  1. golden_manual   — docs/corporate-income-tax-parallel-manual.md 확정·연쇄 매핑
  2. code_hint       — cross_ref_checker._PARALLEL_ARTICLE_HINTS
  3. related_hint    — related_article_hints._RELATED_HINTS (129조 등)
  4. semantic_llm    — 3단계 LLM 쌍별 판별 결과 (match=true, 양방향)
  5. citation        — 인용 그래프 타법 엣지 (정방향: 이 조문이 인용하는 타법 조문)
  6. back_citation   — 인용 그래프 타법 엣지 (역방향: 이 조문을 인용하는 타법 조문)

사용:
  uv run python scripts/build_parallel_matrix.py                    # 스냅샷 재사용
  uv run python scripts/build_parallel_matrix.py --refresh-snapshots
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 콘솔 cp949 인코딩 크래시 방지 (build_graph_all.log 사례)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.cross_ref_checker import _PARALLEL_ARTICLE_HINTS  # noqa: E402
from core.law_api import get_law_text  # noqa: E402
from core.law_freshness import load_manifest  # noqa: E402
from core.parallel_golden import golden_entries  # noqa: E402
from core.parallel_matrix import matrix_key, normalize_jo  # noqa: E402
from core.related_article_hints import _RELATED_HINTS  # noqa: E402

_SNAPSHOT_DIR = ROOT / "data" / "law-snapshots"
_GRAPH_PATH = ROOT / "data" / "law-citation-graph.json"
_ADJUDICATIONS_PATH = ROOT / "data" / "parallel-adjudications.json"
_OUT = ROOT / "data" / "parallel-law-matrix.json"

_SOURCE_PRIORITY = (
    "golden_manual", "code_hint", "related_hint",
    "semantic_llm", "citation", "back_citation",
)

# "제33조제1항제12호" / "제33조의2" / "제33의2조" → (jo, jo_sub)
_ART_RE = re.compile(r"제(?:(\d+)의(\d+)조|(\d+)조(?:의(\d+))?)")


def _article_jo(article_ref: str) -> str:
    """조문 표기에서 API 형식 조번호 추출. 실패 시 ""."""
    m = _ART_RE.search(str(article_ref))
    if not m:
        return ""
    if m.group(1) is not None:
        return f"{m.group(1)}의{m.group(2)}"
    jo, sub = m.group(3), m.group(4)
    return f"{jo}의{sub}" if sub else jo


# ── 0단계: 법령 스냅샷 ────────────────────────────────────────────────────────

def _snapshot_path(law_name: str) -> Path:
    return _SNAPSHOT_DIR / f"{law_name}.json"


def fetch_snapshots(refresh: bool = False) -> dict[str, dict]:
    """manifest 등재 법령 전문을 디스크 스냅샷으로 확보. OCR(OpenAI) 미사용."""
    from config import LAW_API_KEY

    manifest = load_manifest()
    laws = manifest.get("laws", [])
    if not laws:
        print("manifest 비어 있음 — scripts/check_law_freshness.py --update-manifest 먼저 실행")
        return {}

    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, dict] = {}

    for row in laws:
        name, mst = row["name"], str(row["mst"])
        path = _snapshot_path(name)
        if path.is_file() and not refresh:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("MST") == mst and data.get("content_hash") == row.get("content_hash"):
                snapshots[name] = data
                print(f"  재사용 {name} (hash {data.get('content_hash')})")
                continue
        if not LAW_API_KEY:
            print(f"  SKIP {name}: LAW_API_KEY 없음, 스냅샷도 없음")
            continue
        print(f"  조회 {name} (MST {mst})...")
        data = None
        for attempt in range(1, 6):
            try:
                data = get_law_text(mst, LAW_API_KEY, "")
                break
            except Exception as exc:
                wait = attempt * 10
                print(f"    재시도 {attempt}/5 ({exc}) - {wait}초 대기")
                time.sleep(wait)
        if not data:
            print(f"  SKIP {name}: 조회 실패")
            continue
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        snapshots[name] = data
    return snapshots


# ── 1단계: 결정적 레이어 ──────────────────────────────────────────────────────

def _add(
    entries: dict[str, list[dict]],
    key: str,
    entry: dict,
) -> None:
    """중복(target_law + target 조번호) 시 우선순위 높은 소스 유지."""
    bucket = entries.setdefault(key, [])
    new_jo = _article_jo(entry["target_article"])
    for existing in bucket:
        if (
            existing["target_law"] == entry["target_law"]
            and _article_jo(existing["target_article"]) == new_jo
        ):
            old_pri = _SOURCE_PRIORITY.index(existing["source"])
            new_pri = _SOURCE_PRIORITY.index(entry["source"])
            if new_pri < old_pri:
                bucket.remove(existing)
                bucket.append(entry)
            return
    bucket.append(entry)


def build_entries() -> dict[str, list[dict]]:
    entries: dict[str, list[dict]] = {}

    # 1. 골든 매핑 (매뉴얼)
    n_golden = 0
    for key, items in golden_entries().items():
        for item in items:
            _add(entries, key, item)
            n_golden += 1
    print(f"  golden_manual: {n_golden}건")

    # 2. 코드 힌트
    n_hint = 0
    for (src_law, tgt_law, jo), hints in _PARALLEL_ARTICLE_HINTS.items():
        for h in hints:
            _add(entries, matrix_key(src_law, jo), {
                "target_law": tgt_law,
                "target_article": h["article"],
                "relation_type": "parallel_tax_law",
                "confidence": "confirmed",
                "source": "code_hint",
                "reason": h.get("reason", ""),
            })
            n_hint += 1
    print(f"  code_hint: {n_hint}건")

    # 3. 연관 조문 힌트 (같은 법·하위법령 연쇄 포함)
    n_rel = 0
    for (src_law, jo, hang, ho), hints in _RELATED_HINTS.items():
        trigger = f"제{jo}조" + (f"제{hang}항" if hang else "") + (f"제{ho}호" if ho else "")
        for h in hints:
            _add(entries, matrix_key(src_law, jo), {
                "target_law": h["law_name"],
                "target_article": h["article"],
                "relation_type": h.get("relation_type", "related"),
                "confidence": "confirmed",
                "source": "related_hint",
                "reason": h.get("reason", ""),
                "trigger_ref": trigger,
            })
            n_rel += 1
    print(f"  related_hint: {n_rel}건")

    # 4. LLM 쌍별 판별 (3단계, match=true만, 양방향)
    n_sem = 0
    if _ADJUDICATIONS_PATH.is_file():
        adj = json.loads(_ADJUDICATIONS_PATH.read_text(encoding="utf-8"))
        for r in adj.get("results", []):
            if not r.get("match"):
                continue
            jo_a, jo_b = r["jo_a"], r["jo_b"]
            disp_a = f"제{jo_a}조" if "의" not in jo_a else "제{}조의{}".format(*jo_a.split("의", 1))
            disp_b = f"제{jo_b}조" if "의" not in jo_b else "제{}조의{}".format(*jo_b.split("의", 1))
            common = {
                "relation_type": r.get("relation_type", "parallel_tax_law"),
                "confidence": r.get("confidence", "medium"),
                "source": "semantic_llm",
                "reason": r.get("reason", ""),
            }
            _add(entries, matrix_key(r["law_a"], jo_a),
                 {"target_law": r["law_b"], "target_article": disp_b, **common})
            _add(entries, matrix_key(r["law_b"], jo_b),
                 {"target_law": r["law_a"], "target_article": disp_a, **common})
            n_sem += 2
        print(f"  semantic_llm: {n_sem}건 (match {adj.get('match_count', '?')}쌍, "
              f"model {adj.get('model', '?')})")
    else:
        print("  판별 결과 없음 — semantic_llm 레이어 생략")

    # 5·6. 인용 그래프 타법 엣지 (양방향)
    n_cite = n_back = 0
    if _GRAPH_PATH.is_file():
        graph = json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
        for edge in graph.get("edges", []):
            src_law = str(edge.get("source_law", "")).strip()
            tgt_law = str(edge.get("target_law", "")).strip()
            if not src_law or not tgt_law or src_law == tgt_law:
                continue
            src_jo = str(edge.get("source_jo", "")).strip()
            tgt_ref = str(edge.get("target_ref", "")).strip()
            tgt_jo = _article_jo(tgt_ref)
            if not src_jo or not tgt_jo:
                continue
            raw = edge.get("cite_raw", "")
            src_title = edge.get("source_title", "")
            src_disp = (
                f"제{src_jo}조" if "의" not in src_jo
                else "제{}조의{}".format(*src_jo.split("의", 1))
            )
            _add(entries, matrix_key(src_law, src_jo), {
                "target_law": tgt_law,
                "target_article": tgt_ref,
                "relation_type": "citation",
                "confidence": "high",
                "source": "citation",
                "reason": f"명시 인용: {raw}",
            })
            n_cite += 1
            _add(entries, matrix_key(tgt_law, tgt_jo), {
                "target_law": src_law,
                "target_article": src_disp,
                "relation_type": "citation",
                "confidence": "high",
                "source": "back_citation",
                "reason": f"{src_law} {src_disp}({src_title})가 이 조문을 인용: {raw}",
            })
            n_back += 1
        print(f"  citation: {n_cite}건 / back_citation: {n_back}건")
    else:
        print("  인용 그래프 없음 — citation 레이어 생략")

    return entries


# ── 검증 ─────────────────────────────────────────────────────────────────────

def validate_entries(entries: dict[str, list[dict]], snapshots: dict[str, dict]) -> int:
    """스냅샷 보유 법령의 target 조문 존재 검증. validated 플래그 부여."""
    jo_index: dict[str, set[str]] = {
        name: {str(a.get("조번호", "")) for a in data.get("조문목록", [])}
        for name, data in snapshots.items()
    }
    invalid = 0
    for items in entries.values():
        for e in items:
            tgt_law = e["target_law"]
            if tgt_law not in jo_index:
                e["validated"] = None  # 스냅샷 범위 밖 (시행규칙 등)
                continue
            jo = _article_jo(e["target_article"])
            e["validated"] = jo in jo_index[tgt_law]
            if not e["validated"]:
                invalid += 1
                print(f"  [존재 검증 실패] {tgt_law} {e['target_article']} "
                      f"(source={e['source']})")
    return invalid


def assert_golden_recall(entries: dict[str, list[dict]]) -> None:
    """매뉴얼 골든 매핑이 매트릭스에 전부 존재해야 빌드 성공."""
    missing: list[str] = []
    for key, items in golden_entries().items():
        bucket = entries.get(key, [])
        have = {(e["target_law"], _article_jo(e["target_article"])) for e in bucket}
        for item in items:
            want = (item["target_law"], _article_jo(item["target_article"]))
            if want not in have:
                missing.append(f"{key} → {item['target_law']} {item['target_article']}")
    if missing:
        raise AssertionError("골든 매핑 누락:\n" + "\n".join(missing))


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-snapshots", action="store_true",
                        help="스냅샷을 법제처 API에서 다시 받음")
    args = parser.parse_args()

    print("0단계: 법령 스냅샷")
    snapshots = fetch_snapshots(refresh=args.refresh_snapshots)
    print(f"  스냅샷 {len(snapshots)}개 법령\n")

    print("1단계: 결정적 레이어")
    entries = build_entries()

    print("\n검증")
    invalid = validate_entries(entries, snapshots)
    assert_golden_recall(entries)
    print(f"  골든 recall: OK / 존재 검증 실패: {invalid}건")

    manifest = load_manifest()
    law_versions = {
        row["name"]: {
            "mst": str(row["mst"]),
            "content_hash": row.get("content_hash", ""),
            "article_count": row.get("article_count", 0),
        }
        for row in manifest.get("laws", [])
    }
    # 의미 판별이 전수 수행된 법령쌍 — 런타임이 이 쌍에서는 라이브 LLM을 생략한다
    semantic_pairs: list[list[str]] = []
    if _ADJUDICATIONS_PATH.is_file():
        adj = json.loads(_ADJUDICATIONS_PATH.read_text(encoding="utf-8"))
        seen_pairs = {
            tuple(sorted((r["law_a"], r["law_b"])))
            for r in adj.get("results", [])
        }
        semantic_pairs = sorted([list(p) for p in seen_pairs])

    entry_count = sum(len(v) for v in entries.values())
    payload = {
        "built_at": date.today().isoformat(),
        "stage": 3 if semantic_pairs else 1,
        "law_versions": law_versions,
        "semantic_pairs": semantic_pairs,
        "entry_count": entry_count,
        "entries": {k: entries[k] for k in sorted(entries)},
    }
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {_OUT} (키 {len(entries)}개, 엔트리 {entry_count}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""C등급 match 쌍을 상위 모델로 교차 검증.

Haiku 판별 match 중 제목 유사도가 낮은(C등급) 쌍만 Sonnet으로 재판별한다.
양 모델 일치 → 저위험, 불일치 → 사람 검토 대상으로 압축.

사용: uv run python scripts/crosscheck_llm_matches.py
산출물: data/parallel-crosscheck.json (report_llm_matches.py가 반영)
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import ANTHROPIC_API_KEY  # noqa: E402
from scripts.adjudicate_parallel_pairs import (  # noqa: E402
    _load_article_index,
    _parse_result,
    _request_params,
)
from scripts.report_llm_matches import _tier  # noqa: E402

_ADJ_PATH = ROOT / "data" / "parallel-adjudications.json"
_OUT = ROOT / "data" / "parallel-crosscheck.json"

CROSSCHECK_MODEL = "claude-sonnet-4-6"


def main() -> int:
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY 없음")
        return 2
    from anthropic import Anthropic

    data = json.loads(_ADJ_PATH.read_text(encoding="utf-8"))
    targets = [r for r in data.get("results", []) if r.get("match") and _tier(r) == "C"]
    print(f"C등급 {len(targets)}쌍 교차 검증 (model={CROSSCHECK_MODEL})")

    index = _load_article_index()
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    def _check(r: dict) -> dict:
        params = _request_params(r, index)
        params["model"] = CROSSCHECK_MODEL
        resp = client.messages.create(**params)
        text = "".join(b.text for b in resp.content if b.type == "text")
        verdict = _parse_result(text) or {}
        return {
            "law_a": r["law_a"], "jo_a": r["jo_a"],
            "law_b": r["law_b"], "jo_b": r["jo_b"],
            "haiku_match": True,
            "crosscheck_match": bool(verdict.get("match")),
            "crosscheck_confidence": verdict.get("confidence", ""),
            "crosscheck_reason": verdict.get("reason", ""),
        }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_check, r) for r in targets]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 20 == 0:
                print(f"  {i}/{len(targets)}")

    agree = sum(1 for r in results if r["crosscheck_match"])
    payload = {
        "built_at": date.today().isoformat(),
        "model": CROSSCHECK_MODEL,
        "checked": len(results),
        "agree": agree,
        "disagree": len(results) - agree,
        "results": results,
    }
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n일치 {agree}쌍 / 불일치 {len(results) - agree}쌍")
    print(f"저장: {_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""병행법령 매트릭스 빌드 — 3단계: LLM 쌍별 판별 (Claude Batches API).

2단계 후보쌍(data/parallel-candidates-stage2.json)을 쌍별 판별 프롬프트로
Claude Haiku에 묻는다. 두 조문이 입력으로 주어지므로 hallucination이
구조적으로 불가능하고, 컨센서스 중복 호출도 불필요하다.

사용:
  uv run python scripts/adjudicate_parallel_pairs.py --sample 20   # 동기 검증
  uv run python scripts/adjudicate_parallel_pairs.py --submit      # 배치 제출
  uv run python scripts/adjudicate_parallel_pairs.py --fetch       # 결과 회수(폴링)

산출물: data/parallel-adjudications.json
배치 상태: data/parallel-adjudication-batch.json (batch_id)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from config import ANTHROPIC_API_KEY  # noqa: E402

_SNAPSHOT_DIR = ROOT / "data" / "law-snapshots"
_CANDIDATES_PATH = ROOT / "data" / "parallel-candidates-stage2.json"
_BATCH_STATE_PATH = ROOT / "data" / "parallel-adjudication-batch.json"
_OUT = ROOT / "data" / "parallel-adjudications.json"

MODEL = "claude-haiku-4-5"
_BODY_LIMIT = 2500  # 조문 본문 절단 길이 (자)

_SYSTEM = """당신은 대한민국 세법 개정 전문가입니다. 두 법령의 조문 A와 B가 주어집니다.
A 조문이 개정될 때 B 조문도 동일한 취지로 병행 개정을 검토해야 하는 관계인지 판단하세요.

판단 기준:
- 두 조문이 동일한 정책 목적(예: 업무용승용차 비용 한도, 기부금 한도)을 서로 다른 세목·납세자군에 대해 규정하면 match: true
- 법인세법과 소득세법이 같은 항목을 각각 법인/개인사업자에 대해 규율하면 match: true
- 한쪽이 다른 쪽과 같은 취지의 계산방법·정의·적용범위를 두면 match: true (relation_type으로 구분)
- 단순히 같은 세법 분야에 속하거나 일부 용어만 겹치면 match: false
- 인용·준용 관계만 있고 규정 취지가 다르면 match: false (인용 관계는 별도 레이어가 관리)

relation_type:
- parallel_tax_law: 동일 취지를 다른 세목에서 병행 규정
- calculation_rule: 같은 취지의 계산방법·한도 산정
- definition_scope: 같은 취지의 정의·적용범위
- unrelated: match가 false인 경우

reason은 한국어 한 문장으로 작성하세요."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "match": {"type": "boolean"},
        "relation_type": {
            "type": "string",
            "enum": ["parallel_tax_law", "calculation_rule", "definition_scope", "unrelated"],
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string"},
    },
    "required": ["match", "relation_type", "confidence", "reason"],
    "additionalProperties": False,
}


def _jo_display(jo: str) -> str:
    if "의" in jo:
        a, b = jo.split("의", 1)
        return f"제{a}조의{b}"
    return f"제{jo}조"


def _load_article_index() -> dict[tuple[str, str], tuple[str, str]]:
    index: dict[tuple[str, str], tuple[str, str]] = {}
    for path in _SNAPSHOT_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        law = data.get("법령명", path.stem)
        for a in data.get("조문목록", []):
            index[(law, str(a.get("조번호", "")))] = (
                str(a.get("제목", "")),
                str(a.get("내용", "")),
            )
    return index


def _load_candidates() -> list[dict]:
    data = json.loads(_CANDIDATES_PATH.read_text(encoding="utf-8"))
    return data["candidates"]


def _user_content(c: dict, index: dict[tuple[str, str], tuple[str, str]]) -> str:
    ta, ba = index.get((c["law_a"], c["jo_a"]), (c["title_a"], ""))
    tb, bb = index.get((c["law_b"], c["jo_b"]), (c["title_b"], ""))
    return (
        f"[A] {c['law_a']} {_jo_display(c['jo_a'])}({ta})\n{ba[:_BODY_LIMIT]}\n\n"
        f"[B] {c['law_b']} {_jo_display(c['jo_b'])}({tb})\n{bb[:_BODY_LIMIT]}"
    )


def _request_params(c: dict, index: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 512,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": _user_content(c, index)}],
        "output_config": {"format": {"type": "json_schema", "schema": _SCHEMA}},
    }


def _parse_result(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "match" not in data:
        return None
    return data


def cmd_sample(n: int) -> int:
    from anthropic import Anthropic

    candidates = _load_candidates()
    index = _load_article_index()

    # 층화 샘플: 상위 / 경계(최저 점수) / 무작위 중간
    by_score = sorted(candidates, key=lambda c: -c["score"])
    top = by_score[: n // 4]
    low = by_score[-(n // 2):]
    rest = by_score[len(top):-len(low)] if len(by_score) > len(top) + len(low) else []
    rng = random.Random(42)
    mid = rng.sample(rest, min(n - len(top) - len(low), len(rest))) if rest else []
    sample = top + mid + low

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    print(f"샘플 {len(sample)}쌍 동기 판별 (model={MODEL})\n")
    n_match = 0
    for c in sample:
        resp = client.messages.create(**_request_params(c, index))
        text = "".join(b.text for b in resp.content if b.type == "text")
        verdict = _parse_result(text) or {}
        mark = "MATCH " if verdict.get("match") else "no    "
        if verdict.get("match"):
            n_match += 1
        print(f"[{mark}] s={c['score']:>2} {c['law_a']} {_jo_display(c['jo_a'])}({c['title_a']}) "
              f"↔ {c['law_b']} {_jo_display(c['jo_b'])}({c['title_b']})")
        print(f"         {verdict.get('relation_type', '?')}/{verdict.get('confidence', '?')} — "
              f"{verdict.get('reason', '(파싱 실패)')}")
    print(f"\nmatch {n_match}/{len(sample)}")
    return 0


def cmd_submit() -> int:
    from anthropic import Anthropic

    candidates = _load_candidates()
    index = _load_article_index()
    requests = [
        {"custom_id": f"p{i:05d}", "params": _request_params(c, index)}
        for i, c in enumerate(candidates)
    ]
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    batch = client.messages.batches.create(requests=requests)
    state = {
        "batch_id": batch.id,
        "submitted_at": date.today().isoformat(),
        "model": MODEL,
        "request_count": len(requests),
        "candidates_built_at": json.loads(
            _CANDIDATES_PATH.read_text(encoding="utf-8")
        ).get("built_at", ""),
    }
    _BATCH_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"배치 제출: {batch.id} ({len(requests)}건, status={batch.processing_status})")
    print(f"상태 저장: {_BATCH_STATE_PATH}")
    return 0


def cmd_fetch(wait_seconds: int) -> int:
    from anthropic import Anthropic

    if not _BATCH_STATE_PATH.is_file():
        print("배치 상태 파일 없음 — --submit 먼저 실행")
        return 2
    state = json.loads(_BATCH_STATE_PATH.read_text(encoding="utf-8"))
    batch_id = state["batch_id"]
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    deadline = time.monotonic() + wait_seconds
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        print(f"  status={batch.processing_status} "
              f"(succeeded={counts.succeeded}, processing={counts.processing}, "
              f"errored={counts.errored})")
        if batch.processing_status == "ended":
            break
        if time.monotonic() > deadline:
            print("아직 진행 중 — 나중에 --fetch 재실행")
            return 3
        time.sleep(30)

    candidates = _load_candidates()
    results: list[dict] = []
    n_match = n_err = 0
    for item in client.messages.batches.results(batch_id):
        idx = int(item.custom_id[1:])
        c = candidates[idx]
        row = {
            "law_a": c["law_a"], "jo_a": c["jo_a"], "title_a": c["title_a"],
            "law_b": c["law_b"], "jo_b": c["jo_b"], "title_b": c["title_b"],
            "score": c["score"],
        }
        if item.result.type == "succeeded":
            msg = item.result.message
            text = "".join(b.text for b in msg.content if b.type == "text")
            verdict = _parse_result(text)
            if verdict:
                row.update(verdict)
                if verdict.get("match"):
                    n_match += 1
            else:
                row.update({"match": None, "error": "parse_failure"})
                n_err += 1
        else:
            row.update({"match": None, "error": item.result.type})
            n_err += 1
        results.append(row)

    results.sort(key=lambda r: (not r.get("match"), r["law_a"], r["jo_a"]))
    payload = {
        "built_at": date.today().isoformat(),
        "model": state.get("model", MODEL),
        "batch_id": batch_id,
        "result_count": len(results),
        "match_count": n_match,
        "error_count": n_err,
        "results": results,
    }
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {_OUT}")
    print(f"판별 {len(results)}건 — match {n_match}건 / 오류 {n_err}건")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", type=int, metavar="N")
    group.add_argument("--submit", action="store_true")
    group.add_argument("--fetch", action="store_true")
    parser.add_argument("--wait", type=int, default=480, help="--fetch 폴링 최대 대기(초)")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY 없음 — .env 확인")
        return 2
    if args.sample:
        return cmd_sample(args.sample)
    if args.submit:
        return cmd_submit()
    return cmd_fetch(args.wait)


if __name__ == "__main__":
    sys.exit(main())

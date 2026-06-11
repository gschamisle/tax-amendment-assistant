"""3단계 LLM match 쌍 검수 리포트 생성.

제목 유사도로 자동 신뢰/검토 필요를 분류해 docs/parallel-llm-review.md 생성.
- A등급(자동 신뢰): 동의어 정규화 후 제목이 사실상 동일
- B등급(저위험): 제목 토큰 절반 이상 일치
- C등급(검토 권장): 그 외 — 사람이 한 번 볼 가치가 있는 판단 케이스

사용: uv run python scripts/report_llm_matches.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.build_parallel_candidates import _canon, _title_tokens  # noqa: E402

_ADJ_PATH = ROOT / "data" / "parallel-adjudications.json"
_CROSSCHECK_PATH = ROOT / "data" / "parallel-crosscheck.json"
_OUT = ROOT / "docs" / "parallel-llm-review.md"


def _jo_display(jo: str) -> str:
    if "의" in jo:
        a, b = jo.split("의", 1)
        return f"제{a}조의{b}"
    return f"제{jo}조"


def _tier(r: dict) -> str:
    ca, cb = _canon(r["title_a"]), _canon(r["title_b"])
    if ca == cb or (ca and cb and (ca in cb or cb in ca)):
        return "A"
    ta, tb = _title_tokens(r["title_a"]), _title_tokens(r["title_b"])
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        if jac >= 0.5:
            return "B"
    return "C"


def main() -> int:
    data = json.loads(_ADJ_PATH.read_text(encoding="utf-8"))
    matches = [r for r in data.get("results", []) if r.get("match")]
    tiers: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for r in matches:
        tiers[_tier(r)].append(r)

    # 교차 검증 결과 반영: C → C1(양 모델 일치, 저위험) / C2(불일치, 검토 필요)
    crosscheck: dict[tuple[str, str, str, str], dict] = {}
    cc_model = ""
    if _CROSSCHECK_PATH.is_file():
        cc = json.loads(_CROSSCHECK_PATH.read_text(encoding="utf-8"))
        cc_model = cc.get("model", "")
        for r in cc.get("results", []):
            crosscheck[(r["law_a"], r["jo_a"], r["law_b"], r["jo_b"])] = r

    c1: list[dict] = []
    c2: list[tuple[dict, dict]] = []
    for r in tiers["C"]:
        hit = crosscheck.get((r["law_a"], r["jo_a"], r["law_b"], r["jo_b"]))
        if hit is None:
            c2.append((r, {}))
        elif hit["crosscheck_match"]:
            c1.append(r)
        else:
            c2.append((r, hit))

    lines = [
        "# 병행 매트릭스 LLM 판별 검수 리포트",
        "",
        f"생성일 {date.today().isoformat()} / 1차 {data.get('model', '?')} / "
        f"교차 {cc_model or '(미수행)'} / 배치 {data.get('batch_id', '?')}",
        "",
        f"match {len(matches)}쌍 분류: A(제목 동일, 자동 신뢰) {len(tiers['A'])} · "
        f"B(제목 과반 일치) {len(tiers['B'])} · C1(양 모델 일치) {len(c1)} · "
        f"**C2(모델 불일치 — 사람 검토 {len(c2)}쌍)**",
        "",
        "오판 쌍 발견 시: 해당 줄을 이 문서에 기록하고 "
        "`scripts/build_parallel_matrix.py`의 제외 목록에 추가 후 재빌드.",
        "",
        "## C2등급 — 사람 검토 필요 (Haiku는 match, Sonnet은 불일치)",
        "",
    ]
    for r, hit in c2:
        lines.append(
            f"- [ ] {r['law_a']} {_jo_display(r['jo_a'])}({r['title_a']}) ↔ "
            f"{r['law_b']} {_jo_display(r['jo_b'])}({r['title_b']})"
        )
        lines.append(f"  - 1차: {r.get('relation_type')}/{r.get('confidence')} — {r.get('reason', '')}")
        if hit:
            lines.append(f"  - 교차: 불일치 — {hit.get('crosscheck_reason', '')}")

    lines += ["", "## C1등급 — 양 모델 일치 (저위험)", ""]
    for r in c1:
        lines.append(
            f"- {r['law_a']} {_jo_display(r['jo_a'])}({r['title_a']}) ↔ "
            f"{r['law_b']} {_jo_display(r['jo_b'])}({r['title_b']})"
        )
        lines.append(f"  - {r.get('reason', '')}")

    lines += ["", "## B등급 — 저위험 (제목 과반 일치)", ""]
    for r in tiers["B"]:
        lines.append(
            f"- {r['law_a']} {_jo_display(r['jo_a'])}({r['title_a']}) ↔ "
            f"{r['law_b']} {_jo_display(r['jo_b'])}({r['title_b']})"
        )

    lines += ["", "## A등급 — 자동 신뢰 (정규화 후 제목 동일)", ""]
    for r in tiers["A"]:
        lines.append(
            f"- {r['law_a']} {_jo_display(r['jo_a'])} ↔ "
            f"{r['law_b']} {_jo_display(r['jo_b'])} ({r['title_a']})"
        )

    _OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"A(자동 신뢰) {len(tiers['A'])}쌍 / B(저위험) {len(tiers['B'])}쌍 / "
          f"C1(양 모델 일치) {len(c1)}쌍 / C2(사람 검토) {len(c2)}쌍")
    print(f"저장: {_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

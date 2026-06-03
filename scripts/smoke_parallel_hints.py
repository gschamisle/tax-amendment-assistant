"""병행개정 힌트(확정 매핑 + 조특법 JSON) 오프라인 스모크 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.cross_ref_checker import _known_parallel_hints
from core.special_tax_hints import citation_hints_for


def _article_text(jo_label: str, title: str = "") -> str:
    head = f"{jo_label}({title})" if title else jo_label
    return f"{head}\n(본문 생략)"


def _hint_articles(hints: list[dict[str, str]]) -> set[str]:
    return {h.get("article", "") for h in hints}


def _assert_contains(
    hints: list[dict[str, str]],
    expected_article: str,
    label: str,
) -> None:
    arts = _hint_articles(hints)
    assert expected_article in arts, f"{label}: expected {expected_article!r}, got {sorted(arts)}"


def _assert_citation_source(hints: list[dict[str, str]], label: str) -> None:
    for h in hints:
        if h.get("hint_source") == "citation":
            return
    assert False, f"{label}: no citation hint_source in {hints}"


CASES: list[tuple[str, str, str, str, str, bool]] = [
    (
        "조특법→법인세법 (제5조의2→제36조)",
        "조세특례제한법",
        "법인세법",
        _article_text("제5조의2", "중소기업에 대한 특별세액감면"),
        "제36조",
        True,
    ),
    (
        "법인세법→조특법 (제36조 역방향)",
        "법인세법",
        "조세특례제한법",
        _article_text("제36조"),
        "제5조의2",
        True,
    ),
    (
        "소득세법 33조1호6→법인세법 제23조",
        "소득세법",
        "법인세법",
        _article_text("제33조제1항제6호"),
        "제23조",
        False,
    ),
    (
        "법인세법 27조의2→소득세법 33조의2",
        "법인세법",
        "소득세법",
        _article_text("제27조의2", "업무용승용차 관련비용의 손금불산입 특례"),
        "제33조의2",
        False,
    ),
    (
        "법인세법 27조의2→시행령 50조의2",
        "법인세법",
        "법인세법 시행령",
        _article_text("제27조의2", "업무용승용차 관련비용의 손금불산입 특례"),
        "제50조의2",
        False,
    ),
]


def main() -> int:
    failed = 0
    for label, law, parallel, text, expected, need_citation in CASES:
        hints = _known_parallel_hints(law, text, parallel)
        try:
            _assert_contains(hints, expected, label)
            if need_citation:
                _assert_citation_source(hints, label)
            print(f"OK  {label} → {expected} ({len(hints)} hint(s))")
        except AssertionError as e:
            print(f"FAIL {label}: {e}", file=sys.stderr)
            failed += 1

    # JSON 로더 직접 호출
    fwd = citation_hints_for(
        "조세특례제한법",
        "법인세법",
        ["5의2"],
    )
    if not any(h.get("article") == "제36조" for h in fwd):
        print("FAIL citation_hints_for forward 5의2", file=sys.stderr)
        failed += 1
    else:
        print("OK  citation_hints_for(조특법, 법인세법, 5의2) → 제36조")

    rev = citation_hints_for(
        "법인세법",
        "조세특례제한법",
        ["36"],
    )
    if not any("5조의2" in h.get("article", "") for h in rev):
        print("FAIL citation_hints_for reverse 36", file=sys.stderr)
        failed += 1
    else:
        print("OK  citation_hints_for(법인세법, 조특법, 36) → 제5조의2")

    if failed:
        print(f"\n{failed} case(s) failed", file=sys.stderr)
        return 1
    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

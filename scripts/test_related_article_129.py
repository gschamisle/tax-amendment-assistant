"""제129조제1항제3호 개정 시 연관 조문 탐지 테스트."""
from __future__ import annotations

import re
import sys

from core.outline_intent import OutlineIntent, TextReplacement, parse_outline_intent
from core.related_article_hints import lookup_related_hints
from core.related_article_scanner import find_related_article_reviews
from ui.stage1_draft import _sanitize_gpt_related

ART129 = (
    "제129조(원천징수세율) ① 원천징수의무자가 제127조제1항 각 호에 따른 소득을 "
    "지급하여 소득세를 원천징수할 때 적용하는 세율(이하 \"원천징수세율\"이라 한다)은 "
    "다음 각 호의 구분에 따른다.\n"
    "  3. 원천징수대상 사업소득에 대해서는 100분의 3.\n"
    "② (생략)"
)
article = {"조번호": "129", "내용": ART129}
outline = "129조 1항 3호의 원천징수 세율을 현행 3%에서 2%로 하향한다."

EXPECTED = [
    ("소득세법", "73"),
    ("소득세법", "127"),
    ("소득세법", "144"),
    ("소득세법 시행령", "137"),
    ("소득세법 시행령", "184"),
]


def _extract_refs(text: str) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for line in text.splitlines():
        m = re.search(r"(소득세법(?:\s*시행령)?)\s+제(\d+(?:의\d+)?)조", line)
        if m:
            refs.add((m.group(1).replace("  ", " "), m.group(2)))
    return refs


def main() -> int:
    intent = parse_outline_intent(outline, article, "", prefer_gpt=False)
    assert intent.target_ho == "3", intent.target_ho
    assert intent.primary_replacement.old_text == "100분의 3"

    hints = lookup_related_hints("소득세법", "129", "1", "3")
    assert len(hints) == 5, hints

    from config import LAW_API_KEY

    related = find_related_article_reviews("소득세법", article, intent, LAW_API_KEY)
    refs = _extract_refs(related)

    for law, jo in EXPECTED:
        key = (law, jo)
        assert key in refs, f"missing {law} 제{jo}조 in:\n{related}"

    bad = '[검토] 소득세법 시행령 소득세법 제129조: "3%" → "2%"'
    assert _sanitize_gpt_related(bad) == ""

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests for outline intent parsing (offline fixtures)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.outline_intent import (
    OutlineIntent,
    TextReplacement,
    parse_outline_intent,
    _resolve_text_pair,
    _try_regex_intent,
)
from ui.stage1_draft import _deterministic_related_reviews, _sanitize_gpt_related

# 제27조의2 ③~⑤ 일부 (800만원·400만원·제3항 인용 포함)
SAMPLE = """
③ 업무용승용차 관련비용의 손금불산입액은 800만원(1년 미만인 경우 800만원에 월수를 곱한 금액)을 초과할 수 없다.
④ 제3항을 적용할 때 처분손실은 800만원을 한도로 한다.
⑤ 제3항에 따른 금액과 제4항을 적용할 때 800만원 및 400만원을 각각 적용한다.
"""
article = {"조번호": "27의2", "내용": SAMPLE}

cases = [
    ("제3항 800만원을 1,000만원으로 상향한다.", "regex", 3),
    ("③ 한도 천만원으로 올리자", "heuristic", 3),
    ("제3항 한도금액 인상 (800→1000만원)", "heuristic", 3),
]

for outline, expected_source, min_related in cases:
    intent = parse_outline_intent(outline, article, "", prefer_gpt=False)
    related = _deterministic_related_reviews(article, intent)
    n = related.count("\n") + 1 if related else 0
    print("---", outline)
    print(" source:", intent.source, "summary:", intent.summary)
    print(" rep:", intent.primary_replacement)
    print(" related:", n)
    if expected_source:
        assert intent.source == expected_source, intent.source
    assert intent.replacements, outline
    assert n >= min_related, related

# 제129조 3호 100분의 3 → 100분의 2 (요강은 %)
ART129 = (
    "제129조(원천징수세율) ① 원천징수의무자가 ... 따른다.\n"
    "  3. 원천징수대상 사업소득에 대해서는 100분의 3. 다만, ...\n"
    "② (생략)"
)
art129 = {"조번호": "129", "내용": ART129}
outline129 = "129조 1항 3호의 원천징수 세율을 현행 3%에서 2%로 하향한다."
intent129 = parse_outline_intent(outline129, art129, "", prefer_gpt=False)
assert intent129.target_ho == "3", intent129.target_ho
assert intent129.primary_hang == "1", intent129.primary_hang
assert intent129.primary_replacement.old_text == "100분의 3", intent129.primary_replacement
assert intent129.primary_replacement.new_text == "100분의 2", intent129.primary_replacement
related129 = _deterministic_related_reviews(art129, intent129, "소득세법", "")
assert "제127조" in related129, related129
assert "제73조" in related129, related129
noisy = '[검토] 소득세법 시행령 소득세법 제129조: "3%" → "2%" — 연동 검토'
assert _sanitize_gpt_related(noisy) == ""
assert _resolve_text_pair("3%", "2%", ART129) == ("100분의 3", "100분의 2")
print("article129 intent OK")

print("ALL PASS")

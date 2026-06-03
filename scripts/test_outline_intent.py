"""Tests for outline intent parsing (offline fixtures)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.outline_intent import parse_outline_intent, _heuristic_intent, _try_regex_intent
from ui.stage1_draft import _deterministic_related_reviews

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

print("ALL PASS")

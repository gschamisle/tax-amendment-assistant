"""연관 검토 큐 티어·통합 테스트."""
from __future__ import annotations

import sys

from core.outline_intent import OutlineIntent, TextReplacement, parse_outline_intent
from core.related_review_queue import build_review_queue, pending_required_reviews

ART129 = (
    "제129조(원천징수세율) ① 원천징수의무자가 제127조제1항 각 호에 따른 소득을 "
    "지급하여 소득세를 원천징수할 때 적용하는 세율(이하 \"원천징수세율\"이라 한다)은 "
    "다음 각 호의 구분에 따른다.\n"
    "  3. 원천징수대상 사업소득에 대해서는 100분의 3.\n"
    "② (생략)"
)
article = {"조번호": "129", "내용": ART129}
outline = "129조 1항 3호의 원천징수 세율을 현행 3%에서 2%로 하향한다."


def main() -> int:
    intent = parse_outline_intent(outline, article, "", prefer_gpt=False)
    queue = build_review_queue("소득세법", article, intent, "", [], "")
    assert queue, "queue empty"

    hints = [c for c in queue if c.source == "hint"]
    assert len(hints) == 5, hints
    assert all(c.tier == "reference" for c in hints)
    assert all(c.relation_type for c in hints), [c.relation_type for c in hints]

    required_cross = [
        c for c in queue
        if c.tier == "required" and c.is_cross_article()
    ]
    # 그래프/역인용 없을 때도 힌트는 reference로 유지
    pending = pending_required_reviews(queue, set())
    assert isinstance(pending, list)

    gpt_block = '[검토] 소득세법 제127조: "100분의 3" → "100분의 2" — 제129조 직접 인용'
    q2 = build_review_queue("소득세법", article, intent, gpt_block, [], "")
    gpt_req = [c for c in q2 if c.source == "gpt" and c.tier == "required"]
    assert gpt_req, "GPT direct cite should be required"

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

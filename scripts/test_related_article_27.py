"""제27조의2(업무용승용차) 병행·연쇄 검토 골든 테스트."""
from __future__ import annotations

import sys

from core.outline_intent import parse_outline_intent
from core.related_review_queue import build_review_queue

ART27_2 = (
    "제27조의2(업무용승용차 관련비용의 손금불산입 등에 관한 특례) "
    "① 법인이 업무용승용차와 관련하여 지출한 비용 중 대통령령으로 정하는 "
    "금액을 초과하는 금액은 손금에 산입하지 아니한다.\n"
    "③ 제1항에도 불구하고 대통령령으로 정하는 금액의 범위에서 "
    "800만원을 초과하는 금액은 손금에 산입하지 아니한다."
)
article = {"조번호": "27의2", "내용": ART27_2}
outline = "27조의2 제3항 한도를 800만원에서 1,000만원으로 상향한다."

EXPECTED_PARALLEL = {
    ("소득세법", "제33조의2"),
    ("소득세법 시행령", "제78조의3"),
}


def main() -> int:
    intent = parse_outline_intent(outline, article, "", prefer_gpt=False)
    queue = build_review_queue("법인세법", article, intent, "", [], "")
    parallel = [
        (c.law_name, c.article_ref)
        for c in queue
        if c.source == "parallel_hint" and c.tier == "required"
    ]
    found = set(parallel)
    for law, ref in EXPECTED_PARALLEL:
        assert (law, ref) in found, f"missing parallel {law} {ref} in {parallel}"

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

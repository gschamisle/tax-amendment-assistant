"""항 압축·호/목 개정 표시 오프라인 테스트."""
from __future__ import annotations

import sys

from core.article_comparison_format import (
    build_amended_display,
    build_current_display,
    compress_unchanged_hang_lines,
    format_compressed_hang_label,
)
from core.outline_intent import OutlineIntent, TextReplacement


def test_compress_labels() -> None:
    assert format_compressed_hang_label(["①"], "(생략)") == "① (생략)"
    assert format_compressed_hang_label(["①", "②"], "(생략)") == "①·② (생략)"
    assert format_compressed_hang_label(["①", "②", "③", "④"], "(현행과같음)") == "①~④ (현행과같음)"
    lines = ["① (생략)", "② (생략)", "③ 본문"]
    assert compress_unchanged_hang_lines(lines, amended=False) == ["①·② (생략)", "③ 본문"]
    print("compress labels OK")


def test_hang_only() -> None:
    article = {
        "내용": (
            "① 첫 항입니다.\n"
            "② 두 번째 항 800만원 한도.\n"
            "③ 세 번째 항입니다.\n"
            "④ 네 번째 항입니다."
        )
    }
    intent = OutlineIntent(
        target_hangs=["2"],
        replacements=[TextReplacement("800만원", "1,000만원", hangs=["2"])],
        summary="",
        source="test",
    )
    current = build_current_display(article, intent, "")
    assert "①·" not in current or "① (생략)" in current
    assert "① (생략)" in current or "①·" in current
    assert "<del>800만원</del>" in current
    assert "③·④ (생략)" in current or "③~④ (생략)" in current
    compressed = compress_unchanged_hang_lines(
        ["① (생략)", "③ (생략)", "④ (생략)"],
        amended=False,
    )
    assert compressed == ["①~④ (생략)"]

    amended = build_amended_display(
        article,
        intent,
        "② <u>1,000만원</u> 한도.\n① (현행과같음)\n③ (현행과같음)\n④ (현행과같음)",
    )
    assert "① (현행과같음)" in amended or "①·" in amended
    assert "<u>1,000만원</u>" in amended
    print("hang only OK")


def test_ho_only() -> None:
    article = {
        "내용": (
            "① 다음 각 호의 어느 하나에 해당하는 경우에는 손금불산입한다.\n"
            "  1. 첫 번째 호 800만원 한도.\n"
            "  2. 두 번째 호.\n"
            "② 다른 항 전체."
        )
    }
    intent = OutlineIntent(
        target_hangs=["1"],
        replacements=[TextReplacement("800만원", "1,000만원", hangs=["1"])],
        summary="",
        source="test",
        target_ho="1",
    )
    current = build_current_display(article, intent, "")
    assert "① 다음 각 호" in current
    assert "2. 두 번째 호." in current
    assert "<del>800만원</del>" in current
    assert "② (생략)" in current

    amended = build_amended_display(article, intent, "① (현행과같음)\n② (현행과같음)")
    assert amended.count("①") == 1
    assert "<u>1,000만원</u>" in amended
    assert "2. (현행과같음)" in amended
    assert "- - -" not in amended.split("②")[0] or "<u>" in amended
    print("ho only OK")


def test_article129_ho3_inline_hang() -> None:
    article = {
        "내용": (
            "제129조(원천징수세율) ① 원천징수의무자가 제127조제1항 각 호에 따른 소득을 "
            "지급하여 소득세를 원천징수할 때 적용하는 세율(이하 \"원천징수세율\"이라 한다)은 "
            "다음 각 호의 구분에 따른다.\n"
            "  1. 근로소득에 대해서는 100분의 6 이상 100분의 45 이하.\n"
            "  2. 퇴직소득에 대해서는 100분의 3.\n"
            "  3. 원천징수대상 사업소득에 대해서는 100분의 3. "
            "다만, 외국인 직업운동가가 한국표준산업분류에 따른 스포츠 클럽 운영업 중 "
            "프로스포츠구단과의 계약에 따라 용역을 제공하고 받는 소득에 대해서는 100분의 20으로 한다.\n"
            "  4. 기타소득에 대해서는 100분의 20.\n"
            "  5. 연금소득에 대해서는 100분의 5.\n"
            "② 다른 항."
        )
    }
    intent = OutlineIntent(
        target_hangs=["1"],
        replacements=[TextReplacement("100분의 3", "100분의 2", hangs=["1"])],
        summary="",
        source="test",
        target_ho="3",
    )
    gpt = (
        "제129조(원천징수세율) ① ...\n"
        "  1. (현행과같음)\n"
        "  2. (현행과같음)\n"
        "  3. ... <u>100분의 2</u> ...\n"
        "  4. (현행과같음)\n"
        "② (현행과같음)"
    )
    amended = build_amended_display(article, intent, gpt)
    assert amended.count("①") == 1
    assert "제129조(원천징수세율)" in amended
    assert "다음 각 호의 구분에 따른다" in amended
    assert "1. (현행과같음)" in amended
    assert "2. (현행과같음)" in amended
    assert "<u>100분의 2</u>" in amended
    assert "4. (현행과같음)" in amended
    assert "5. (현행과같음)" in amended
    assert "② (현행과같음)" in amended
    dash_blob = amended.split("②")[0].count("- - -")
    assert dash_blob < 5, f"excessive dashes: {dash_blob}"
    print("article129 ho3 OK")


def main() -> int:
    test_compress_labels()
    test_hang_only()
    test_ho_only()
    test_article129_ho3_inline_hang()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

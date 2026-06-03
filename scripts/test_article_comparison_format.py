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
    assert "(현행과같음)" not in amended.split("②")[0] or "----" in amended
    assert "<u>1,000만원</u>" in amended
    assert "2." not in amended.split("<u>")[0] or "----" in amended
    print("ho only OK")


def main() -> int:
    test_compress_labels()
    test_hang_only()
    test_ho_only()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

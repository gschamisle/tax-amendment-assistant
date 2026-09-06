# -*- coding: utf-8 -*-
"""문서 추출 진입점 오프라인 테스트 (네트워크·kordoc 실행 없이)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import core.document_text as dt


def test_plain_text() -> None:
    tmp = Path(tempfile.mkdtemp())
    for suffix in (".md", ".txt"):
        p = tmp / f"a{suffix}"
        p.write_text("소득세법 일부를 다음과 같이 개정한다.\n", encoding="utf-8")
        assert "소득세법" in dt.extract(p)
    print("  md/txt 추출 OK")


def test_missing_file_is_loud() -> None:
    """조용히 빈 문자열을 돌려주면 '개정문을 못 찾았다'로만 보여 원인을 못 찾는다."""
    try:
        dt.extract(Path(tempfile.mkdtemp()) / "없는파일.pdf")
    except dt.ExtractError as exc:
        assert "파일이 없습니다" in str(exc)
    else:
        raise AssertionError("없는 파일인데 예외가 없다")
    print("  없는 파일 오류 표면화 OK")


def test_unsupported_suffix() -> None:
    tmp = Path(tempfile.mkdtemp()) / "a.docx"
    tmp.write_text("x", encoding="utf-8")
    try:
        dt.extract(tmp)
    except dt.ExtractError as exc:
        assert "지원하지 않는 형식" in str(exc), exc
    else:
        raise AssertionError("미지원 형식인데 예외가 없다")
    print("  미지원 형식 오류 OK")


def test_pdf_uses_cache(monkeypatch=None) -> None:
    """같은 PDF를 다시 올려도 재변환하지 않는다 (조특법안 변환은 수십 초)."""
    tmp = Path(tempfile.mkdtemp())
    pdf = tmp / "bill.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    cache = pdf.with_suffix(pdf.suffix + ".kordoc.md")
    cache.write_text("변환 결과", encoding="utf-8")

    calls = []
    orig = dt.subprocess.run
    dt.subprocess.run = lambda *a, **k: calls.append(a) or orig(["cmd", "/c", "exit", "0"], **k)
    try:
        text = dt.extract(pdf)
    finally:
        dt.subprocess.run = orig
    assert text == "변환 결과", text
    assert not calls, "캐시가 있는데 kordoc을 다시 불렀다"
    print("  PDF 변환 캐시 OK")


def test_pdf_without_kordoc_explains() -> None:
    """Node가 없는 환경에서 원인을 알려야 한다 — 폐쇄망에서 흔한 상황."""
    tmp = Path(tempfile.mkdtemp())
    pdf = tmp / "b.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    orig = dt.kordoc_available
    dt.kordoc_available = lambda: False
    try:
        dt.extract(pdf)
    except dt.ExtractError as exc:
        assert "kordoc" in str(exc) and "HWPX" in str(exc), exc
    else:
        raise AssertionError("kordoc이 없는데 예외가 없다")
    finally:
        dt.kordoc_available = orig
    print("  kordoc 부재 안내 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (document_text, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

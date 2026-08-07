"""의견 수집 어댑터 테스트 — HTML/CSV 파싱, generic 폴백, 개인정보 마스킹."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.opinion_source import (  # noqa: E402
    OpinionRecord,
    author_fingerprint,
    dedupe_records,
    load_from_files,
    mask_author,
    parse_generic_html,
    parse_list_html,
    records_from_rows,
)

FIXTURES = ROOT / "data" / "opinion-fixtures"


def test_selector_parsing() -> None:
    html = (FIXTURES / "sample-list.html").read_text(encoding="utf-8")
    records = parse_list_html(html, "87936")

    assert len(records) == 4, f"expected 4 records, got {len(records)}"
    ids = [r.opinion_id for r in records]
    assert ids == ["1001", "1002", "1003", "1004"], ids

    first = records[0]
    assert "종합부동산세는 폐지" in first.body, first.body
    assert first.posted_at == "2026-07-15", first.posted_at
    assert first.bill_id == "87936"
    assert first.stance_raw == "반대", first.stance_raw
    assert first.title == "1세대 1주택 종합부동산세 폐지 요청", first.title

    # 날짜 표기가 흔들려도 정규화된다
    assert records[2].posted_at == "2026-07-17", records[2].posted_at
    assert records[3].posted_at == "2026-07-18", records[3].posted_at
    print("  selector parsing OK")


def test_author_is_never_stored() -> None:
    html = (FIXTURES / "sample-list.html").read_text(encoding="utf-8")
    records = parse_list_html(html, "87936")

    assert records[0].author_masked == "홍*동", records[0].author_masked
    assert records[1].author_masked == "김*수", records[1].author_masked
    assert records[2].author_masked == "이*", records[2].author_masked
    assert records[3].author_masked == "박", records[3].author_masked

    # 실명이 어떤 필드로도 새어나가면 안 된다
    for record in records:
        blob = " ".join(str(v) for v in record.to_dict().values())
        for real_name in ("홍길동", "김철수", "이영"):
            assert real_name not in blob, f"실명 유출: {real_name} in {record.opinion_id}"

    assert author_fingerprint("홍길동") == author_fingerprint("홍 길동")
    assert author_fingerprint("홍길동") != author_fingerprint("김철수")
    assert author_fingerprint("") == ""
    assert mask_author("") == ""
    print("  author masking OK")


def test_generic_fallback() -> None:
    html = (FIXTURES / "sample-generic.html").read_text(encoding="utf-8")

    # 설정 셀렉터로는 잡히지 않는 구조 → parse_list_html이 스스로 폴백한다
    records = parse_list_html(html, "87936")
    assert len(records) == 4, f"expected 4 fallback records, got {len(records)}"
    assert all(r.body for r in records)
    assert any("세부담 상한" in r.body for r in records), [r.body for r in records]
    assert records[0].posted_at == "2026-07-20", records[0].posted_at
    assert records[0].author_masked == "김*희", records[0].author_masked
    # 라벨 텍스트는 본문에서 걷어낸다
    assert "작성자:" not in records[0].body, records[0].body

    direct = parse_generic_html(html, "87936")
    assert len(direct) == len(records)
    # 동일 입력 → 동일 ID (합성 ID도 결정적이어야 재수집 시 중복이 안 생긴다)
    assert [r.opinion_id for r in direct] == [r.opinion_id for r in records]
    print("  generic fallback OK")


def test_csv_and_rows() -> None:
    records = load_from_files([FIXTURES / "sample-opinions.csv"], "87936")
    assert len(records) == 8, len(records)
    assert records[0].opinion_id == "2001", records[0].opinion_id
    assert records[0].posted_at == "2026-07-24", records[0].posted_at
    assert records[0].author_masked == "윤*람", records[0].author_masked
    assert "폐지" in records[0].body

    # 영문 키(JSON API 응답 형태)도 같은 매퍼가 처리한다
    rows = [{"opnId": "3001", "regDt": "2026/08/01", "wrtrNm": "테스터", "opnCn": "세율을 인하해 주십시오."}]
    mapped = records_from_rows(rows, "87936")
    assert mapped[0].opinion_id == "3001"
    assert mapped[0].posted_at == "2026-08-01", mapped[0].posted_at
    assert mapped[0].body == "세율을 인하해 주십시오."

    # 본문이 없는 행은 버린다
    assert records_from_rows([{"opnId": "9", "opnCn": ""}], "87936") == []
    print("  csv / row mapping OK")


def test_dedupe_and_empty() -> None:
    a = OpinionRecord(opinion_id="1", bill_id="x", body="가")
    b = OpinionRecord(opinion_id="1", bill_id="x", body="나")
    c = OpinionRecord(opinion_id="2", bill_id="x", body="다")
    deduped = dedupe_records([a, b, c])
    assert [r.opinion_id for r in deduped] == ["1", "2"]
    assert deduped[0].body == "가", "먼저 수집한 레코드를 남겨야 한다"

    assert parse_list_html("", "x") == []
    assert parse_list_html("<html><body><p>없음</p></body></html>", "x") == []
    print("  dedupe / empty input OK")


def main() -> int:
    print("opinion_source tests")
    test_selector_parsing()
    test_author_is_never_stored()
    test_generic_fallback()
    test_csv_and_rows()
    test_dedupe_and_empty()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

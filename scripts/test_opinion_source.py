"""의견 수집 어댑터 테스트 — HTML/CSV 파싱, generic 폴백, 개인정보 마스킹."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.opinion_source import (  # noqa: E402
    DEFAULT_SELECTORS,
    OpinionRecord,
    author_fingerprint,
    dedupe_records,
    fetch_opinions,
    load_from_files,
    mask_author,
    parse_generic_html,
    parse_list_html,
    records_from_rows,
)

FIXTURES = ROOT / "data" / "opinion-fixtures"


def test_selector_parsing() -> None:
    html = (FIXTURES / "sample-list.html").read_text(encoding="utf-8")
    # DEFAULT_SELECTORS를 명시한다. 인자를 비우면 load_selectors()가
    # data/opinion-selectors.json(실사이트 설정)을 읽어, 픽스처와 무관한
    # 로컬 설정에 테스트 결과가 좌우된다.
    records = parse_list_html(html, "87936", DEFAULT_SELECTORS)

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
    records = parse_list_html(html, "87936", DEFAULT_SELECTORS)

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


def test_target_items_merge_on_dedupe() -> None:
    """사이트는 의견 1건을 대상 개정항목마다 한 행씩 내려준다.

    접지 않으면 한 사람 의견이 여러 번 집계되고, 그냥 접으면 어느 항목에 달린
    의견인지가 사라진다 — 접되 대상은 합쳐야 한다.
    """
    def rec(oid: str, title: str) -> OpinionRecord:
        return OpinionRecord(opinion_id=oid, bill_id="87936", body="반대합니다", title=title)

    merged = dedupe_records([
        rec("a", "가. 납세의무자 조정"),
        rec("a", "나. 기본공제금액 조정"),
        rec("a", "가. 납세의무자 조정"),   # 같은 대상 반복은 한 번만
        rec("b", "다. 세율 조정"),
    ])
    assert len(merged) == 2, merged
    assert merged[0].title == "가. 납세의무자 조정 ; 나. 기본공제금액 조정", merged[0].title
    assert merged[1].title == "다. 세율 조정", merged[1].title
    print("  대상 개정항목 병합 OK")


def test_incremental_stops_at_known() -> None:
    """증분 수집: 이미 가진 의견에 닿으면 멈추고, 새 의견만 돌려준다."""
    page = (FIXTURES / "sample-list.html").read_text(encoding="utf-8")
    known = parse_list_html(page, "87936", DEFAULT_SELECTORS)
    assert known, "픽스처 파싱 실패"

    calls: list[int] = []

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        text = page

    class _Sess:
        def get(self, url, **kw):
            calls.append(1)
            return _Resp()

    report = fetch_opinions(
        "87936", session=_Sess(), check_robots=False, delay=0,
        selectors=DEFAULT_SELECTORS, known=known, max_pages=50,
    )
    assert report.records == [], report.records          # 전부 아는 의견
    # 같은 페이지가 반복 응답되면 즉시 멈춘다 — max_pages까지 긁으면 안 된다
    assert len(calls) <= 2, f"곧바로 멈춰야 하는데 {len(calls)}회 요청"
    assert report.stopped_reason, "중단 사유가 기록돼야 한다"

    # known이 비면 종전대로 전량 수집한다
    fresh = fetch_opinions(
        "87936", session=_Sess(), check_robots=False, delay=0,
        selectors=DEFAULT_SELECTORS, max_pages=10,
    )
    assert len(fresh.records) == len(known), fresh.records
    print("  증분 수집 조기 중단 OK")


def test_barren_page_does_not_end_crawl() -> None:
    """새 의견이 없는 페이지가 끼어도 크롤이 끝나면 안 된다.

    의견 1건이 대상 개정항목마다 행을 차지해 한 페이지가 통째로 한 의견의
    연속 행일 수 있다(실측: 소득세법안 15페이지 = 20행 전부 같은 의견).
    거기서 멈추면 뒤쪽 의견을 통째로 놓친다 — 233건 대 709건 차이였다.
    """
    page1 = (FIXTURES / "sample-list.html").read_text(encoding="utf-8")
    # 2페이지 = 이미 본 의견 하나가 대상별로 반복된 페이지(새 의견 0건).
    # 1페이지와 '내용이 같지는' 않다 — 그건 페이지가 안 넘어간 경우라 별개로 멈춘다.
    page2 = page1
    for old in ("1001", "1002", "1003"):
        page2 = page2.replace(f'data-opn-id="{old}"', 'data-opn-id="1004"')
    page3 = page1.replace('data-opn-id="100', 'data-opn-id="900')
    pages = {1: page1, 2: page2, 3: page3, 4: ""}
    calls: list[int] = []

    class _Sess:
        def get(self, url, **kw):
            page = int(url.rsplit("=", 1)[-1])
            calls.append(page)
            body = pages.get(page, "")
            return type("R", (), {
                "status_code": 200,
                "headers": {"Content-Type": "text/html"},
                "text": body,
            })()

    report = fetch_opinions(
        "87936", session=_Sess(), check_robots=False, delay=0,
        selectors=DEFAULT_SELECTORS, max_pages=10,
    )
    ids = {r.opinion_id for r in report.records}
    assert "9001" in ids, f"3페이지의 새 의견을 놓쳤다: {sorted(ids)}"
    assert len(report.records) == 8, [r.opinion_id for r in report.records]
    print("  빈 페이지 관용 OK")


def main() -> int:
    print("opinion_source tests")
    test_selector_parsing()
    test_author_is_never_stored()
    test_generic_fallback()
    test_csv_and_rows()
    test_dedupe_and_empty()
    test_target_items_merge_on_dedupe()
    test_incremental_stops_at_known()
    test_barren_page_does_not_end_crawl()
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

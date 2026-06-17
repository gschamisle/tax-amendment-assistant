"""별표 추출·역연관 테스트 (오프라인, 라이브 API 불필요)."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

from core.byeolpyo import byeolpyo_label, related_byeolpyo
from core.law_api import _extract_byeolpyo

_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<법령>
  <별표단위>
    <별표번호>0001</별표번호><별표가지번호>00</별표가지번호>
    <별표구분>별표</별표구분>
    <별표제목>의료취약지역(제7조제4호 관련)</별표제목>
    <별표서식파일링크>/LSW/flDownload.do?flSeq=1</별표서식파일링크>
  </별표단위>
  <별표단위>
    <별표번호>0002</별표번호><별표가지번호>02</별표가지번호>
    <별표구분>서식</별표구분>
    <별표제목>과세표준 신고서[「소득세법」 제118조의15 관련]</별표제목>
  </별표단위>
</법령>"""


def test_extract_byeolpyo() -> None:
    items = _extract_byeolpyo(ET.fromstring(_FIXTURE))
    assert len(items) == 2, items

    b1 = items[0]
    assert b1["번호"] == "1" and b1["구분"] == "별표", b1
    # 별표제목의 '(제7조제4호 관련)' → 관련조문 파싱
    assert b1["관련조문"] == [{"jo": "7", "jo_sub": "", "hang": "", "ho": "4", "law_name": ""}], b1["관련조문"]
    assert b1["hwp"].endswith("flSeq=1")

    b2 = items[1]
    # 별표번호 0002 + 가지번호 02 → "2의2"
    assert b2["번호"] == "2의2" and b2["구분"] == "서식", b2
    # 낫표 타법 인용도 잡힌다 (「소득세법」 제118조의15)
    r = b2["관련조문"][0]
    assert (r["jo"], r["jo_sub"], r["law_name"]) == ("118", "15", "소득세법"), r


def test_related_byeolpyo() -> None:
    law_data = {
        "법령명": "소득세법 시행규칙",
        "별표목록": _extract_byeolpyo(ET.fromstring(_FIXTURE)),
    }
    # 같은 법 제7조 → 별표 1 포착
    hits = related_byeolpyo(law_data, "7")
    assert len(hits) == 1 and byeolpyo_label(hits[0]) == "별표 1", hits

    # 무관한 조문은 없음
    assert related_byeolpyo(law_data, "9") == []

    # 별표2(서식)는 「소득세법」(모법)을 가리킴 — 현재 법령이 시행규칙이라 cross-law 제외
    assert related_byeolpyo(law_data, "118", "15") == []

    # 현재 법령이 소득세법이면 같은 법 인용으로 인정
    law_data2 = dict(law_data, 법령명="소득세법")
    assert len(related_byeolpyo(law_data2, "118", "15")) == 1


def main() -> int:
    test_extract_byeolpyo()
    test_related_byeolpyo()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

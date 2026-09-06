# -*- coding: utf-8 -*-
"""법령 약칭·법령 관계도 오프라인 테스트."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core import law_abbrev as A
from core import law_map

ROOT = Path(__file__).resolve().parents[1]


def test_abbreviations() -> None:
    """실무 관용 약칭. 규칙 유추로는 안 나오는 것들이라 표로 고정한다."""
    for full_name, short in [
        ("소득세법", "소득법"), ("소득세법 시행령", "소득령"), ("소득세법 시행규칙", "소득칙"),
        ("법인세법", "법인법"), ("부가가치세법 시행규칙", "부가칙"),
        ("국세기본법 시행령", "국기령"), ("국제조세조정에 관한 법률", "국조법"),
        ("국제조세조정에 관한 법률 시행령", "국조령"),
        ("상속세 및 증여세법", "상증법"), ("조세특례제한법", "조특법"),
        ("종합부동산세법 시행령", "종부령"), ("농어촌특별세법", "농특법"),
        ("국세징수법", "국징법"), ("관세법 시행규칙", "관세칙"),
    ]:
        assert A.law(full_name) == short, (full_name, A.law(full_name))
    print("  법령 약칭 OK")


def test_unknown_law_is_left_alone() -> None:
    """표에 없으면 원문 그대로 — 틀린 약칭을 지어내지 않는다."""
    assert A.law("어떤이상한법") == "어떤이상한법"
    assert A.law("") == ""
    assert not A.is_known("어떤이상한법")
    # '관세법'은 약칭이 원문과 같다 — 문자열 비교로 미등록을 판정할 수 없다
    assert A.law("관세법") == "관세법" and A.is_known("관세법")
    print("  미등록 법령 원문 유지 OK")


def test_article_marks() -> None:
    assert A.article("제73조의2") == "§73의2"
    assert A.article("제73조의2제1항") == "§73의2제1항"
    assert A.article("제95조") == "§95"
    assert A.article("별표 1") == "별표 1"          # 조문 표기가 아니면 그대로
    assert A.jo_key("73의2") == "§73의2"
    assert A.full("소득세법 시행령", "제73조의2") == "소득령 §73의2"
    print("  조문 표기 OK")


def test_manifest_laws_all_covered() -> None:
    """추적 중인 32개 법령은 전부 약칭이 있어야 한다 — 하나라도 빠지면 도표에 긴 이름이 섞인다."""
    manifest = json.loads((ROOT / "data" / "law-snapshot-manifest.json").read_text(encoding="utf-8"))
    missing = [e["name"] for e in manifest["laws"] if not A.is_known(e["name"])]
    assert not missing, f"약칭 미등록: {missing}"
    print(f"  manifest {len(manifest['laws'])}개 법령 전부 약칭 보유 OK")


def test_family_grouping() -> None:
    assert law_map.family("소득세법 시행령") == "소득세법"
    assert law_map.family("소득세법 시행규칙") == "소득세법"
    assert law_map.family("소득세법") == "소득세법"
    print("  법령군 묶기 OK")


def test_cross_family_filter() -> None:
    """시행령→모법 인용은 위임 구조상 당연해서 정보가 없는데 건수가 압도적이다."""
    same = law_map.build(min_edge=1, cross_family_only=False)
    cross = law_map.build(min_edge=1, cross_family_only=True)
    assert len(cross["edges"]) < len(same["edges"]), (len(cross["edges"]), len(same["edges"]))
    assert all(law_map.family(a) != law_map.family(b) for a, b in cross["edges"]), "같은 군이 남았다"
    print("  법령군 간 필터 OK")


def test_render_is_deterministic() -> None:
    data = law_map.build()
    a, b = law_map.render_svg(data), law_map.render_svg(law_map.build())
    assert a == b, "두 번 그린 결과가 다르다"
    assert "소득법" in a and "조특법" in a and "제" not in a.split("aria-label")[1][:200]
    print("  법령 관계도 결정적 렌더 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (law_abbrev/law_map, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

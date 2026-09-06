# -*- coding: utf-8 -*-
"""조문 관계도(ego graph) 오프라인 테스트."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.ego_graph import SECTORS, build, render_svg, summary_line

_SAMPLE = {
    "law_name": "법인세법",
    "target_label": "제27조의2",
    "cited": [{"법령명": "소득세법", "조문": "제33조의2"}],
    "junyong": [{"법령명": "법인세법", "조문": "제25조"}],
    "back_cited": [
        {"법령명": "법인세법 시행령", "조번호": "50의2", "제목": "업무용승용차"},
        {"법령명": "법인세법 시행령", "조번호": "50의3", "제목": "관련"},
        {"법령명": "조세특례제한법", "조번호": "104", "제목": "특례"},
    ],
    "parallel": [{"법령명": "소득세법", "조문": "제33조의2", "근거": "golden_manual"}],
    "byeolpyo": [],
    "cited_byeolpyo": [],
}


def test_grouping_by_law() -> None:
    """노드는 조문이 아니라 법령이다 — 역인용 수십 건이면 라벨이 겹친다."""
    ego = build(_SAMPLE)
    back = ego["nodes"]["back_cited"]
    assert [n.law for n in back] == ["법인령", "조특법"], back   # 약칭 표기
    assert back[0].count == 2 and back[0].articles == ["§50의2", "§50의3"], back[0]
    # 인용과 준용은 한 사분면으로 합친다
    assert ego["totals"]["cited"] == 2, ego["totals"]
    assert ego["totals"]["parallel"] == 1
    print("  법령 단위 묶기 OK")


def test_sort_is_deterministic() -> None:
    """건수 내림차순 → 이름 오름차순. 난수·해시 순서에 기대지 않는다."""
    rows = [{"법령명": n, "조번호": "1"} for n in ("나법", "가법", "다법")]
    rows += [{"법령명": "가법", "조번호": "2"}]
    ego = build({"law_name": "X", "target_label": "제1조", "back_cited": rows})
    assert [n.law for n in ego["nodes"]["back_cited"]] == ["가법", "나법", "다법"]
    print("  정렬 결정성 OK")


def test_render_is_byte_identical() -> None:
    """같은 입력이면 같은 바이트 — 보고자료로 나가는 그림이라 흔들리면 안 된다."""
    a, b = render_svg(build(_SAMPLE)), render_svg(build(_SAMPLE))
    assert a == b, "두 번 그린 결과가 다르다"
    assert a.startswith("<svg") and a.endswith("</svg>")
    for _kind, title, _color, _angle in SECTORS:
        assert title in a, f"사분면 제목 누락: {title}"
    assert "법인법 §27의2" in a
    print("  SVG 결정적 렌더 OK")


def test_escapes_markup() -> None:
    """법령명·제목이 SVG를 깨거나 마크업으로 새어나가면 안 된다."""
    svg = render_svg(build({
        "law_name": "<script>", "target_label": "제1조",
        "back_cited": [{"법령명": "a<b>&c", "조번호": "1"}],
    }))
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "a&lt;b&gt;&amp;c" in svg
    print("  마크업 이스케이프 OK")


def test_empty_sectors_keep_labels() -> None:
    """관계가 없다는 사실도 정보다 — 사분면 제목은 0이어도 남긴다."""
    ego = build({"law_name": "소득세법", "target_label": "제1조"})
    svg = render_svg(ego)
    assert "역인용 0" in svg and "병행 0" in svg, svg[:400]
    assert summary_line(ego) == "연관 조문이 없습니다."
    print("  빈 사분면 표기 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (ego_graph, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

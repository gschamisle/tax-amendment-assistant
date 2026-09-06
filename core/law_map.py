"""법령 단위 관계도 — 32개 법령을 노드로, 인용 건수를 굵기로.

조문 단위 전체 그래프(노드 5,602)는 노드-링크로 읽히지 않는다. 그런데 **법령
단위로 접으면 노드가 32개**라 한 장에 온전히 들어간다. 잃는 것은 "어느 조문"이고
얻는 것은 "어느 법령군이 서로 얽혀 있나" — 개정 범위를 잡을 때 먼저 봐야 하는 게
후자다.

배치는 원형 고정이다(법령명 사전순). 힘기반이 아니라서 같은 데이터면 같은 그림이
나오고, 법령이 늘거나 줄어도 나머지 위치가 통째로 흔들리지 않는다.
"""
from __future__ import annotations

import html
import json
import math
from collections import Counter
from pathlib import Path

from core import law_abbrev

ROOT = Path(__file__).resolve().parents[1]
_GRAPH = ROOT / "data" / "law-citation-graph.json"

# 이 굵기 미만은 그리지 않는다. 1~2건짜리 인용까지 전부 그으면 32노드도 뭉갠다.
DEFAULT_MIN_EDGE = 8


def family(law_name: str) -> str:
    """'소득세법 시행령' → '소득세법'. 모법·시행령·시행규칙을 한 군으로 묶는다."""
    name = str(law_name).strip()
    for suffix in ("시행규칙", "시행령"):
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def build(
    min_edge: int = DEFAULT_MIN_EDGE,
    laws: list[str] | None = None,
    cross_family_only: bool = True,
) -> dict:
    """법령쌍별 인용 건수.

    cross_family_only가 기본 True인 이유: 시행령이 모법을 인용하는 건 위임 구조상
    당연해서 정보가 없는데, 건수가 압도적이라(조특령→조특법 2,728건) 나머지를
    전부 가린다. 법령군 간 관계만 남겨야 '어디까지 번지는가'가 보인다.
    """
    edges = json.loads(_GRAPH.read_text(encoding="utf-8"))["edges"]
    pair: Counter[tuple[str, str]] = Counter()
    size: Counter[str] = Counter()
    for e in edges:
        a, b = str(e.get("source_law", "")), str(e.get("target_law", ""))
        if not a or not b:
            continue
        if laws and (a not in laws or b not in laws):
            continue
        size[a] += 1
        if a == b:
            continue
        if cross_family_only and family(a) == family(b):
            continue
        pair[(a, b)] += 1

    names = sorted(size)
    kept = {k: v for k, v in pair.items() if v >= min_edge}
    return {
        "laws": names,
        "self_counts": dict(size),
        "edges": dict(sorted(kept.items(), key=lambda kv: -kv[1])),
        "min_edge": min_edge,
        "cross_family_only": cross_family_only,
    }


def _esc(t: str) -> str:
    return html.escape(str(t), quote=True)


# 법령군별 색 — 모법·시행령·시행규칙을 한 색으로 묶어 계열이 보이게
_FAMILY_COLORS: tuple[tuple[str, str], ...] = (
    ("소득세법", "#1e40af"), ("법인세법", "#15803d"), ("부가가치세법", "#b45309"),
    ("상속세 및 증여세법", "#7c3aed"), ("조세특례제한법", "#be123c"),
    ("국제조세조정에 관한 법률", "#0f766e"), ("관세법", "#a16207"),
    ("국세기본법", "#475569"), ("국세징수법", "#64748b"),
    ("농어촌특별세법", "#9d174d"), ("종합부동산세법", "#1d4ed8"),
)


def _color(law_name: str) -> str:
    for stem, color in _FAMILY_COLORS:
        if law_name.startswith(stem):
            return color
    return "#52627a"


def render_svg(data: dict, width: int = 1000, height: int = 1000) -> str:
    laws = data["laws"]
    if not laws:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"></svg>'

    cx, cy, r = width / 2, height / 2, min(width, height) / 2 - 132
    pos: dict[str, tuple[float, float]] = {}
    for i, name in enumerate(laws):
        a = math.radians(-90 + 360 * i / len(laws))
        pos[name] = (cx + math.cos(a) * r, cy + math.sin(a) * r)

    top = max(data["edges"].values(), default=1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" role="img" aria-label="법령 간 인용 관계도">',
        '<style>'
        '.nm{font:600 13px Pretendard,sans-serif}'
        '.ct{font:10.5px Pretendard,sans-serif;fill:#52627a}'
        '.hd{font:700 15px Pretendard,sans-serif;fill:#0f172a}'
        '.lg{font:11px Pretendard,sans-serif;fill:#52627a}'
        '</style>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text class="hd" x="{width/2:.0f}" y="34" text-anchor="middle">'
        f'법령 간 인용 관계 — {len(laws)}개 법령</text>',
        f'<text class="lg" x="{width/2:.0f}" y="54" text-anchor="middle">'
        f'선 굵기 = 인용 건수 ({data["min_edge"]}건 이상)'
        + (" · 법령군 간 인용만 (시행령→모법 제외)" if data.get("cross_family_only") else "")
        + ' · 배치는 이름순 고정</text>',
    ]

    # 선을 먼저 — 노드가 위에 오도록
    for (a, b), n in data["edges"].items():
        (x1, y1), (x2, y2) = pos[a], pos[b]
        # 중심을 향해 살짝 휘게 해 반대편 선과 구분되게
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        qx, qy = mx + (cx - mx) * 0.35, my + (cy - my) * 0.35
        parts.append(
            f'<path d="M{x1:.0f},{y1:.0f} Q{qx:.0f},{qy:.0f} {x2:.0f},{y2:.0f}" '
            f'fill="none" stroke="{_color(a)}" stroke-width="{0.6 + 5 * n / top:.1f}" '
            f'stroke-opacity="0.30"/>'
        )

    for name in laws:
        x, y = pos[name]
        color = _color(name)
        deg = sum(n for (a, b), n in data["edges"].items() if name in (a, b))
        rr = 6 + min(deg / top * 12, 12)
        anchor = "start" if x >= cx else "end"
        dx = rr + 7 if x >= cx else -(rr + 7)
        parts += [
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rr:.0f}" fill="{color}" '
            f'fill-opacity="0.20" stroke="{color}" stroke-width="1.6"/>',
            f'<text class="nm" x="{x:.0f}" y="{y - 1:.0f}" dx="{dx:.0f}" fill="{color}" '
            f'text-anchor="{anchor}">{_esc(law_abbrev.law(name))}</text>',
            f'<text class="ct" x="{x:.0f}" y="{y + 12:.0f}" dx="{dx:.0f}" '
            f'text-anchor="{anchor}">{data["self_counts"].get(name, 0)}건</text>',
        ]

    parts.append("</svg>")
    return "".join(parts)


def top_pairs(data: dict, limit: int = 12) -> list[tuple[str, str, int]]:
    return [(law_abbrev.law(a), law_abbrev.law(b), n)
            for (a, b), n in list(data["edges"].items())[:limit]]

"""조문 1개의 연관 관계를 한 장으로 — 결정적 SVG.

표는 관계 유형마다 블록이 갈려서 "이 조문이 어느 쪽으로 무겁게 얽혀 있나"가
한눈에 안 들어온다. 1-hop만 그리면 그 판단이 즉시 된다.

**힘기반 배치를 쓰지 않는다.** 산출물이 보고자료로 나가는 도구라 같은 입력이면
같은 그림이 나와야 한다(저장소 제1원칙). 관계 유형을 사분면에 고정하고 그 안에서
건수·이름 순으로 쌓는다 — 난수도 반복 계산도 없다.

**1-hop만 그린다.** 실측(29,302엣지) 기준 1-hop 이웃은 중앙값 3·90퍼센타일 13이라
읽히지만, 2-hop은 중앙값 34·90퍼센타일 162로 이미 뭉갠다. 전체 그래프(노드 5,602)는
조특법 허브 몇 개가 화면을 지배해 정작 볼 것을 가린다.

**노드는 조문이 아니라 법령이다.** 역인용이 40건을 넘는 조문이 흔한데 조문마다
점을 찍으면 라벨이 겹친다. 법령으로 묶고 조번호는 칩으로 단다.
"""
from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# 관계 유형 → (표시명, 색, 사분면 각도(도), 설명)
# 각도는 12시=270°(위) 기준 SVG 좌표계.
SECTORS: tuple[tuple[str, str, str, float], ...] = (
    ("parallel", "병행", "#7c3aed", 270.0),      # 위 — 같은 취지, 함께 고쳐야
    ("cited", "인용·준용", "#1e40af", 0.0),       # 오른쪽 — 이 조문이 가리키는 곳
    ("byeolpyo", "별표", "#b45309", 90.0),        # 아래 — 서식·별표
    ("back_cited", "역인용", "#15803d", 180.0),   # 왼쪽 — 이 조문을 가리키는 곳
)
_SECTOR_SPREAD = 62.0        # 사분면 안에서 벌리는 각도 폭
_R_INNER, _R_STEP = 132.0, 74.0
_MAX_CHIPS = 5


@dataclass
class LawNode:
    """한 사분면 안의 법령 하나."""

    kind: str
    law: str
    articles: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.articles)


def _jo_label(jo: str) -> str:
    parts = str(jo).split("의")
    if not parts[0].isdigit():
        return str(jo)
    return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")


def build(relations: dict) -> dict:
    """analyze_article_relations 결과 → 사분면별 법령 노드.

    입력을 그대로 받는다. 데이터 배관을 새로 놓지 않으려는 것 —
    화면과 CLI가 같은 관계 판정을 쓰게 해야 둘이 어긋나지 않는다.
    """
    buckets: dict[str, list[dict]] = {
        "parallel": list(relations.get("parallel") or []),
        "cited": list(relations.get("cited") or []) + list(relations.get("junyong") or []),
        "byeolpyo": list(relations.get("byeolpyo") or []) + list(relations.get("cited_byeolpyo") or []),
        "back_cited": list(relations.get("back_cited") or []),
    }

    nodes: dict[str, list[LawNode]] = {}
    for kind, rows in buckets.items():
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            law = str(row.get("법령명") or relations.get("law_name") or "")
            ref = row.get("조문") or row.get("별표") or _jo_label(str(row.get("조번호", "")))
            ref = str(ref).strip()
            if ref and ref not in grouped[law]:
                grouped[law].append(ref)
        # 건수 많은 순 → 이름 순. 난수 없이 항상 같은 순서가 나오도록.
        nodes[kind] = [
            LawNode(kind, law, arts)
            for law, arts in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ]
    return {
        "center": f"{relations.get('law_name', '')} {relations.get('target_label', '')}".strip(),
        "nodes": nodes,
        "totals": {k: sum(n.count for n in v) for k, v in nodes.items()},
    }


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def render_svg(ego: dict, width: int = 940, height: int = 620) -> str:
    """결정적 SVG 문자열. 같은 입력이면 같은 바이트가 나온다."""
    cx, cy = width / 2, height / 2
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" role="img" aria-label="조문 연관 관계도">',
        '<style>'
        '.ttl{font:600 13px Pretendard,sans-serif}'
        '.sub{font:11px Pretendard,sans-serif;fill:#52627a}'
        '.chip{font:10.5px Pretendard,sans-serif;fill:#0f172a}'
        '.ctr{font:700 15px Pretendard,sans-serif;fill:#0f172a}'
        '.lbl{font:600 11px Pretendard,sans-serif}'
        '</style>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    for kind, title, color, angle in SECTORS:
        items = ego["nodes"].get(kind, [])
        total = ego["totals"].get(kind, 0)
        rad = math.radians(angle)
        # 사분면 제목 — 건수가 0이어도 자리를 남긴다(없다는 사실도 정보다)
        tx, ty = cx + math.cos(rad) * 96, cy + math.sin(rad) * 96
        parts.append(
            f'<text class="lbl" x="{tx:.0f}" y="{ty:.0f}" fill="{color}" '
            f'text-anchor="middle">{_esc(title)} {total}</text>'
        )
        if not items:
            continue

        step = _SECTOR_SPREAD / max(len(items) - 1, 1) if len(items) > 1 else 0
        start = angle - (_SECTOR_SPREAD / 2 if len(items) > 1 else 0)
        for i, node in enumerate(items):
            a = math.radians(start + step * i)
            r = _R_INNER + _R_STEP * (i % 2)          # 지그재그로 라벨 겹침 방지
            x, y = cx + math.cos(a) * r, cy + math.sin(a) * r
            parts.append(
                f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{x:.0f}" y2="{y:.0f}" '
                f'stroke="{color}" stroke-width="{min(1 + node.count / 6, 4):.1f}" '
                f'stroke-opacity="0.35"/>'
            )
            rr = min(11 + node.count * 1.4, 26)
            anchor = "start" if math.cos(a) >= 0 else "end"
            dx = rr + 6 if math.cos(a) >= 0 else -(rr + 6)
            chips = ", ".join(node.articles[:_MAX_CHIPS])
            if node.count > _MAX_CHIPS:
                chips += f" 외 {node.count - _MAX_CHIPS}"
            parts += [
                f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rr:.0f}" fill="{color}" '
                f'fill-opacity="0.14" stroke="{color}" stroke-width="1.4"/>',
                f'<text class="ttl" x="{x:.0f}" y="{y - 2:.0f}" dx="{dx:.0f}" '
                f'fill="{color}" text-anchor="{anchor}">{_esc(node.law)} · {node.count}</text>',
                f'<text class="chip" x="{x:.0f}" y="{y + 12:.0f}" dx="{dx:.0f}" '
                f'text-anchor="{anchor}">{_esc(chips)}</text>',
            ]

    parts += [
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="54" fill="#f6f8fb" '
        f'stroke="#1e40af" stroke-width="2"/>',
        f'<text class="ctr" x="{cx:.0f}" y="{cy + 5:.0f}" text-anchor="middle">'
        f'{_esc(ego["center"])}</text>',
        "</svg>",
    ]
    return "".join(parts)


def summary_line(ego: dict) -> str:
    """한 줄 요약 — 그림 없이도 무게중심을 알 수 있게."""
    counts = Counter({k: v for k, v in ego["totals"].items() if v})
    if not counts:
        return "연관 조문이 없습니다."
    label = {k: t for k, t, _c, _a in SECTORS}
    return " · ".join(f"{label[k]} {n}건" for k, n in counts.most_common())

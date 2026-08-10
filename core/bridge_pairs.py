"""다리 법령을 통한 짝조문 도출 — 인용 그래프만으로, LLM 없이.

국제조세조정법·조세특례제한법 같은 법은 한 조문 안에서 소득세법 조문과 법인세법
조문을 **나란히 인용**한다.

    국조법 제4조  → 소득세법 제41조(부당행위계산) + 법인세법 제52조(부당행위계산의 부인)
    국조법 제11조 → 소득세법 제156조 계열(비거주자) + 법인세법 제98조 계열(외국법인)

같은 조문에서 함께 인용됐다는 것은 그 둘이 개인↔법인으로 대응한다는 뜻이고,
그 판단을 내린 것은 추정 알고리즘이 아니라 **입법자 자신**이다. 제목·용어
유사도보다 근거가 세고, 배치 판별과 달리 비용이 들지 않는다.

제목 유사도로 국조법·조특법을 본법과 직접 맞대면 절차어(결정·경정·징수·감면)만
걸린다 — 관계의 성질이 병행이 아니라 준용·특례이기 때문이다. 다리로 쓰는 것이
그 법들을 활용하는 올바른 방식이다.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_GRAPH = ROOT / "data" / "law-citation-graph.json"
_SNAPSHOTS = ROOT / "data" / "law-snapshots"

# 기본 다리 법령. 본법 과세를 준용·특례로 끌어쓰면서 개인·법인 양쪽을 함께 언급한다.
DEFAULT_BRIDGES: tuple[str, ...] = ("국제조세조정에 관한 법률", "조세특례제한법")
DEFAULT_SIDES: tuple[str, str] = ("소득세법", "법인세법")

# 한 조문이 한쪽 법을 이만큼 넘게 인용하면 '나열'이라 짝 신호로 보기 어렵다.
# (조특법에는 감면 대상 조문을 수십 개 늘어놓는 조문이 있다)
MAX_REFS_PER_SIDE = 6

_JO_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def jo_key(ref: str) -> str:
    m = _JO_RE.match(str(ref).strip())
    if not m:
        return ""
    return f"{m.group(1)}의{m.group(2)}" if m.group(2) else m.group(1)


def jo_label(key: str) -> str:
    parts = str(key).split("의")
    return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")


def article_titles(law: str) -> dict[str, str]:
    """스냅샷에서 조번호 → 제목. 목록을 사람이 판단하려면 제목이 있어야 한다."""
    path = _SNAPSHOTS / f"{law}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(a.get("조번호", "")): str(a.get("제목", "")).strip()
            for a in data.get("조문목록", [])}


@dataclass
class BridgePair:
    """다리를 통해 도출된 짝 후보 하나."""

    law_a: str
    jo_a: str
    law_b: str
    jo_b: str
    bridges: list[tuple[str, str]] = field(default_factory=list)   # (다리 법령, 다리 조)

    @property
    def weight(self) -> int:
        return len(self.bridges)


def extract(
    bridges: tuple[str, ...] = DEFAULT_BRIDGES,
    sides: tuple[str, str] = DEFAULT_SIDES,
    max_refs: int = MAX_REFS_PER_SIDE,
) -> list[BridgePair]:
    """다리 법령의 조문별 공동 인용에서 짝 후보를 뽑는다."""
    edges = json.loads(_GRAPH.read_text(encoding="utf-8"))["edges"]
    law_a, law_b = sides

    # (다리 법령, 다리 조) → {법: {조}}
    cited: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {law_a: set(), law_b: set()}
    )
    for e in edges:
        src = str(e.get("source_law", ""))
        tgt = str(e.get("target_law", ""))
        if src not in bridges or tgt not in (law_a, law_b):
            continue
        key = jo_key(str(e.get("target_ref", "")))
        if key:
            cited[(src, str(e.get("source_jo", "")))][tgt].add(key)

    found: dict[tuple[str, str], BridgePair] = {}
    for (bridge_law, bridge_jo), refs in cited.items():
        a_set, b_set = refs[law_a], refs[law_b]
        if not a_set or not b_set:
            continue
        if len(a_set) > max_refs or len(b_set) > max_refs:
            continue                       # 나열형 조문 — 짝 신호가 희석된다
        for ja in sorted(a_set):
            for jb in sorted(b_set):
                pair = found.get((ja, jb))
                if pair is None:
                    pair = BridgePair(law_a, ja, law_b, jb)
                    found[(ja, jb)] = pair
                pair.bridges.append((bridge_law, bridge_jo))

    return sorted(found.values(), key=lambda p: (-p.weight, _sort_key(p.jo_a), _sort_key(p.jo_b)))


def _sort_key(jo: str) -> tuple:
    parts = str(jo).split("의")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return (10**9, 0)


def already_in_matrix(pair: BridgePair) -> bool:
    """이미 매트릭스에 병행 관계로 등재된 쌍인지."""
    from core.parallel_matrix import parallel_hits

    for hit in parallel_hits(pair.law_a, pair.jo_a):
        if hit.get("source") in ("citation", "back_citation"):
            continue
        if str(hit.get("target_law")) == pair.law_b and jo_key(
            str(hit.get("target_article", ""))
        ) == pair.jo_b:
            return True
    return False

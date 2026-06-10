"""병행법령 매트릭스 빌드 — 2단계: 후보쌍 생성 (LLM 호출 없음).

같은 위계의 병행 법령 쌍(법↔법, 시행령↔시행령)에서 전 조문쌍을 스코어링해
3단계 LLM 판별 대상 후보를 추출한다. 기존 런타임의 "키워드 매칭 상한 20개"
컷을 두지 않는다 — 임계값은 골든 매핑 recall 100%를 만족하도록 보정한다.

산출물: data/parallel-candidates-stage2.json
입력: data/law-snapshots/ (0단계), data/parallel-law-matrix.json (1단계)

사용:
  uv run python scripts/build_parallel_candidates.py
  uv run python scripts/build_parallel_candidates.py --min-score 4   # 임계값 실험
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from config import KEYWORD_SYNONYMS  # noqa: E402
from core.cross_ref_checker import _CORE_PARALLEL_TERMS  # noqa: E402
from core.parallel_golden import golden_direct_pairs, golden_group_pairs  # noqa: E402
from scripts.build_parallel_matrix import _article_jo  # noqa: E402

_SNAPSHOT_DIR = ROOT / "data" / "law-snapshots"
_MATRIX_PATH = ROOT / "data" / "parallel-law-matrix.json"
_OUT = ROOT / "data" / "parallel-candidates-stage2.json"

# 같은 위계의 병행 법령 쌍 (조특법은 special_tax 파이프라인이 별도 담당)
_LAW_PAIRS: tuple[tuple[str, str], ...] = (
    ("법인세법", "소득세법"),
    ("법인세법 시행령", "소득세법 시행령"),
    ("법인세법", "부가가치세법"),
    ("법인세법 시행령", "부가가치세법 시행령"),
)

# 매뉴얼 §4의 핵심어 + 코드 핵심어 (정규화 전 표기)
_EXTRA_CORE_TERMS: frozenset[str] = frozenset({
    "세액공제", "세액감면", "익금", "총수입금액", "한도", "특례",
    "감가상각", "내용연수", "상각방법", "상각범위액", "즉시상각",
    "대손금", "대손세액", "원천징수", "충당금", "준비금",
    "과세표준", "신고조정", "상각부인", "시부인", "의제상각",
    "중고자산", "잔존가액",
})

# 본문·교차 시그널에서 제외하는 범용 핵심어 (제목 매칭에서만 사용)
_WEAK_CORE_TERMS: frozenset[str] = frozenset({"한도", "특례", "과세표준"})

_TITLE_STOPWORDS: frozenset[str] = frozenset({
    "등", "및", "그", "밖에", "관한", "대한", "경우", "것", "위한", "따른",
})


def _build_canon_map() -> list[tuple[str, str]]:
    """동의어 그룹 → 대표어 치환 목록 (긴 표기 우선). union-find로 그룹 병합."""
    parent: dict[str, str] = {}

    def find(t: str) -> str:
        parent.setdefault(t, t)
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for key, vals in KEYWORD_SYNONYMS.items():
        k = key.replace(" ", "")
        for v in vals:
            union(k, v.replace(" ", ""))

    groups: dict[str, set[str]] = {}
    for term in parent:
        groups.setdefault(find(term), set()).add(term)

    repl: list[tuple[str, str]] = []
    for terms in groups.values():
        canon = min(sorted(terms))
        for t in terms:
            if t != canon:
                repl.append((t, canon))
    repl.sort(key=lambda x: len(x[0]), reverse=True)
    return repl


_CANON_REPL = _build_canon_map()


def _canon(text: str) -> str:
    text = text.replace(" ", "")
    for old, new in _CANON_REPL:
        text = text.replace(old, new)
    return text


def _canon_core_terms() -> frozenset[str]:
    return frozenset(_canon(t) for t in (_CORE_PARALLEL_TERMS | _EXTRA_CORE_TERMS))


_CORE = _canon_core_terms()
_STRONG_CORE = frozenset(_CORE - {_canon(t) for t in _WEAK_CORE_TERMS})
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def _title_tokens(title: str) -> set[str]:
    tokens: set[str] = set()
    for tok in _TOKEN_RE.findall(title):
        tok = _canon(tok)
        if tok.endswith("의") and len(tok) > 2:
            tok = tok[:-1]
        if len(tok) >= 2 and tok not in _TITLE_STOPWORDS:
            tokens.add(tok)
    return tokens


def _core_in(text_canon: str) -> set[str]:
    return {t for t in _CORE if t in text_canon}


class _Article:
    __slots__ = (
        "jo", "title", "title_canon", "title_tokens",
        "core_title", "strong_body", "strong_title",
    )

    def __init__(self, jo: str, title: str, body: str) -> None:
        self.jo = jo
        self.title = title
        self.title_canon = _canon(title)
        self.title_tokens = _title_tokens(title)
        self.core_title = _core_in(self.title_canon)
        self.strong_title = self.core_title & _STRONG_CORE
        self.strong_body = _core_in(_canon(body)) & _STRONG_CORE


def _load_articles(law_name: str) -> list[_Article]:
    path = _SNAPSHOT_DIR / f"{law_name}.json"
    if not path.is_file():
        raise SystemExit(f"스냅샷 없음: {path} — build_parallel_matrix.py 먼저 실행")
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[_Article] = []
    for a in data.get("조문목록", []):
        jo = str(a.get("조번호", "")).strip()
        title = str(a.get("제목", "")).strip()
        body = str(a.get("내용", ""))
        if not jo:
            continue
        if not title and len(body) < 30:  # 삭제 조문 등
            continue
        out.append(_Article(jo, title, body))
    return out


def _score(a: _Article, b: _Article) -> tuple[int, list[str]]:
    """시그널: ① 제목 핵심어 공유 ② 제목 토큰 공유 ③ 강한 핵심어 본문 공유
    ④ 한쪽 제목의 강한 핵심어가 상대 본문에 등장 (교차)."""
    shared_core_title = a.core_title & b.core_title
    shared_strong_title = shared_core_title & _STRONG_CORE
    shared_weak_title = shared_core_title - _STRONG_CORE
    shared_tokens = (a.title_tokens & b.title_tokens) - shared_core_title
    shared_strong_body = a.strong_body & b.strong_body
    cross = 0
    if a.strong_title & b.strong_body:
        cross += 1
    if b.strong_title & a.strong_body:
        cross += 1
    score = (
        3 * len(shared_strong_title)
        + len(shared_weak_title)  # 특례·한도 등 범용어는 토큰 수준 가중치만
        + len(shared_tokens)
        + min(len(shared_strong_body), 3)
        + cross
    )
    shared = sorted(shared_core_title) + sorted(shared_tokens) + sorted(shared_strong_body)
    return score, shared


_CONFIRMED_SOURCES = frozenset({"golden_manual", "code_hint"})


def _matrix_pairs() -> tuple[
    set[tuple[str, str, str, str]],
    set[tuple[str, str, str, str]],
]:
    """매트릭스 기존 쌍 (전체, 확정앵커) — 양방향 등록."""
    pairs: set[tuple[str, str, str, str]] = set()
    anchors: set[tuple[str, str, str, str]] = set()
    if not _MATRIX_PATH.is_file():
        return pairs, anchors
    data = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    for key, items in data.get("entries", {}).items():
        law_a, jo_a = key.split("|", 1)
        for e in items:
            jo_b = _article_jo(e["target_article"])
            if not jo_b:
                continue
            both = {(law_a, jo_a, e["target_law"], jo_b),
                    (e["target_law"], jo_b, law_a, jo_a)}
            pairs |= both
            if e.get("source") in _CONFIRMED_SOURCES:
                anchors |= both
    return pairs, anchors


def _anchor_cells(
    anchors: set[tuple[str, str, str, str]],
    law_a: str,
    arts_a: list[_Article],
    law_b: str,
    arts_b: list[_Article],
) -> set[tuple[int, int]]:
    """확정 앵커쌍의 ±1 조문 인덱스 이웃 셀 — 구조적 평행성 시그널."""
    idx_a = {a.jo: i for i, a in enumerate(arts_a)}
    idx_b = {b.jo: i for i, b in enumerate(arts_b)}
    cells: set[tuple[int, int]] = set()
    for la, ja, lb, jb in anchors:
        if la != law_a or lb != law_b:
            continue
        ia, ib = idx_a.get(ja), idx_b.get(jb)
        if ia is None or ib is None:
            continue
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                cells.add((ia + da, ib + db))
    return cells


def _orient(pairs: set[tuple[str, str, str, str]]) -> set[tuple[str, str, str, str]]:
    """골든 쌍을 _LAW_PAIRS 평가 방향으로 정규화 (범위 밖 쌍은 제외)."""
    pair_order = {frozenset(p): p for p in _LAW_PAIRS}
    out: set[tuple[str, str, str, str]] = set()
    for law_a, jo_a, law_b, jo_b in pairs:
        order = pair_order.get(frozenset((law_a, law_b)))
        if not order:
            continue
        if law_a == order[0]:
            out.add((law_a, jo_a, law_b, jo_b))
        else:
            out.add((law_b, jo_b, law_a, jo_a))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=int, default=3)
    args = parser.parse_args()

    articles = {name: _load_articles(name) for pair in _LAW_PAIRS for name in pair}
    for name, arts in articles.items():
        print(f"  {name}: {len(arts)}개 조문")

    known, anchors = _matrix_pairs()
    direct = _orient(golden_direct_pairs())
    group = _orient(golden_group_pairs())

    candidates: list[dict] = []
    golden_scores: dict[tuple[str, str, str, str], int] = {}
    stats: list[str] = []

    for law_a, law_b in _LAW_PAIRS:
        arts_a, arts_b = articles[law_a], articles[law_b]
        cells = _anchor_cells(anchors, law_a, arts_a, law_b, arts_b)
        n_pair = n_new = 0
        for (ia, a), (ib, b) in product(enumerate(arts_a), enumerate(arts_b)):
            score, shared = _score(a, b)
            if (ia, ib) in cells:
                score += 1  # 확정 앵커 인접 — 구조적 평행성
            ident = (law_a, a.jo, law_b, b.jo)
            if ident in direct or ident in group:
                golden_scores[ident] = max(golden_scores.get(ident, 0), score)
            if score < args.min_score:
                continue
            n_pair += 1
            if ident in known:
                continue  # 1단계에서 이미 확보된 쌍 — LLM 판별 불필요
            n_new += 1
            candidates.append({
                "law_a": law_a, "jo_a": a.jo, "title_a": a.title,
                "law_b": law_b, "jo_b": b.jo, "title_b": b.title,
                "score": score, "shared_terms": shared,
            })
        stats.append(f"  {law_a} ↔ {law_b}: 통과 {n_pair}쌍 (신규 {n_new})")

    print("\n후보 생성 결과")
    for line in stats:
        print(line)

    # 보정 검증 — 직접 병행쌍(§1·§2)은 엄격(빌드 실패), 그룹쌍(§3)은 경고만.
    # 그룹쌍은 이미 매트릭스에 confirmed로 등재되어 런타임 누락은 없음.
    def _report(tier: str, pairs: set[tuple[str, str, str, str]]) -> list[str]:
        missed: list[str] = []
        for ident in sorted(pairs):
            sc = golden_scores.get(ident)
            label = f"{ident[0]} {ident[1]} ↔ {ident[2]} {ident[3]}"
            if sc is None:
                missed.append(label + " (조문 미발견)")
                print(f"  [없음] {tier} {label}")
            elif sc < args.min_score:
                missed.append(f"{label} (score={sc})")
                print(f"  [MISS] {tier} {label} (score={sc})")
            else:
                print(f"  [OK ] {tier} {label} (score={sc})")
        return missed

    print(f"\n골든 보정 (직접 {len(direct)}쌍 / 그룹 {len(group)}쌍, 임계값 {args.min_score})")
    direct_missed = _report("직접", direct)
    group_missed = _report("그룹", group)
    if direct_missed:
        raise AssertionError(
            "직접 병행쌍 누락 — 시그널/임계값 보정 필요:\n" + "\n".join(direct_missed)
        )
    if group_missed:
        print(f"\n  경고: 그룹쌍 {len(group_missed)}건 임계값 미달 "
              "(매트릭스에는 confirmed로 등재됨)")

    candidates.sort(key=lambda c: -c["score"])
    payload = {
        "built_at": date.today().isoformat(),
        "law_pairs": [list(p) for p in _LAW_PAIRS],
        "min_score": args.min_score,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    _OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {_OUT} (신규 후보 {len(candidates)}쌍)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

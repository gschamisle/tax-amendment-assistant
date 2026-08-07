"""입법예고 의견 군집화 — 결정적 레이어 (신규 의존성 0).

같은 말을 하는 의견을 묶어 건수 순으로 정렬하는 것이 목적이다. 결과가 실행할 때마다
달라지면 보고자료로 쓸 수 없으므로 **전 과정이 결정적**이다(난수·해시 시드 의존 없음,
파이썬 내장 `hash()` 대신 crc32 사용).

3단 구조:

  1. 완전 중복  — 정규화 텍스트 해시로 묶는다. 복붙 의견이 코퍼스의 절반을 차지하는
                 게 정상이라, 여기서 N이 크게 줄어 이후 단계가 싸진다.
  2. 근사 중복  — MinHash + LSH로 후보쌍만 뽑아 Jaccard ≥ dup_threshold 검증.
  3. 유사 의견  — 문자 3-gram TF-IDF 코사인 ≥ threshold. 희귀 n-gram 역색인으로
                 후보를 좁혀 전수 비교(n²)를 피한다.

세 단계가 만든 간선을 union-find로 이어 연결요소를 군집으로 삼는다. 체이닝 과병합은
"큰데 응집도 낮은 군집만 임계값을 올려 재분할"하는 적응형 단계로 억제한다.
"""
from __future__ import annotations

import math
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from core.opinion_normalize import char_ngrams, norm_text, word_terms_with_bigrams

# ── 기본 파라미터 ─────────────────────────────────────────────────────────────
DEFAULT_THRESHOLD = 0.45      # 유사 의견 코사인 임계값
DEFAULT_DUP_THRESHOLD = 0.80  # 근사 중복 Jaccard 임계값
NGRAM_N = 3
MINHASH_PERMS = 64
MINHASH_BANDS = 16            # 밴드당 4개 → Jaccard 0.8 부근에서 민감
TOP_TERMS_PER_DOC = 30        # 역색인 블로킹에 쓸 고가중치 term 수
MAX_POSTINGS = 1500           # 이보다 긴 posting list는 블로킹에서 제외
MEDOID_SAMPLE = 80            # 대표의견 계산 시 비교할 최대 변형 수
SPLIT_MAX_SHARE = 0.35        # 전체의 이 비율을 넘는 군집은 재분할 검토
SPLIT_MIN_COHESION = 0.55     # 응집도가 이보다 낮을 때만 재분할
SPLIT_STEP = 0.10
SPLIT_ROUNDS = 2

_MERSENNE = (1 << 61) - 1


@dataclass
class OpinionDoc:
    """군집화 입력 — 의견 1건."""
    doc_id: str
    text: str


@dataclass
class Cluster:
    """군집 1개. size가 곧 '의견 건수'다."""
    cluster_id: int
    size: int
    member_ids: list[str]
    medoid_id: str
    medoid_text: str
    exemplar_ids: list[str]
    top_terms: list[str]
    cohesion: float
    variant_count: int          # 서로 다른 정규화 텍스트 수
    exact_dup_max: int          # 가장 큰 완전중복 덩어리 크기


@dataclass
class ClusterResult:
    clusters: list[Cluster]     # size 내림차순
    total: int
    unique_texts: int
    threshold: float
    borderline_pairs: list[tuple[str, str, float]] = field(default_factory=list)

    def top(self, n: int) -> list[Cluster]:
        return self.clusters[:n]

    def coverage(self, n: int) -> float:
        """상위 n개 군집이 전체 의견에서 차지하는 비율."""
        if not self.total:
            return 0.0
        return sum(c.size for c in self.clusters[:n]) / self.total


# ── union-find ────────────────────────────────────────────────────────────────

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# ── 변형(고유 텍스트) ─────────────────────────────────────────────────────────

@dataclass
class _Variant:
    index: int
    rep_id: str
    member_ids: list[str]
    text: str
    norm: str
    grams: set[str]
    vec: dict[str, float] = field(default_factory=dict)

    @property
    def weight(self) -> int:
        return len(self.member_ids)


def _build_variants(docs: list[OpinionDoc]) -> tuple[list[_Variant], list[OpinionDoc]]:
    """완전 중복(정규화 텍스트 동일)을 하나의 변형으로 접는다.

    정규화 결과가 빈 문자열인 의견(이모지·기호뿐)은 유사도 계산에서 빼고 따로 돌려준다.
    """
    buckets: dict[str, list[OpinionDoc]] = defaultdict(list)
    empties: list[OpinionDoc] = []
    for doc in docs:
        norm = norm_text(doc.text)
        if not norm:
            empties.append(doc)
            continue
        buckets[norm].append(doc)

    variants: list[_Variant] = []
    # 정규화 텍스트 기준 정렬 → 실행 순서와 무관하게 항상 같은 인덱스가 나온다.
    for norm in sorted(buckets):
        group = sorted(buckets[norm], key=lambda d: d.doc_id)
        variants.append(
            _Variant(
                index=len(variants),
                rep_id=group[0].doc_id,
                member_ids=[d.doc_id for d in group],
                text=group[0].text,
                norm=norm,
                grams=set(char_ngrams(group[0].text, NGRAM_N)),
            )
        )
    return variants, empties


# ── TF-IDF ────────────────────────────────────────────────────────────────────

def _build_vectors(variants: list[_Variant]) -> None:
    """변형별 문자 n-gram TF-IDF 벡터(L2 정규화)를 채운다.

    df는 변형 기준으로 센다. 복붙 800건을 800으로 세면 그 문구의 idf가 0에 수렴해
    정작 가장 중요한 덩어리를 구분하지 못한다.
    """
    n = len(variants)
    if not n:
        return
    df: Counter[str] = Counter()
    tfs: list[Counter[str]] = []
    for v in variants:
        tf = char_ngrams(v.text, NGRAM_N)
        tfs.append(tf)
        df.update(tf.keys())

    for v, tf in zip(variants, tfs):
        vec: dict[str, float] = {}
        for gram, count in tf.items():
            idf = math.log((n + 1) / (df[gram] + 1)) + 1.0
            vec[gram] = (1.0 + math.log(count)) * idf
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm:
            v.vec = {g: w / norm for g, w in vec.items()}
        else:
            v.vec = {}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """L2 정규화 벡터의 코사인 = 공통 n-gram 가중치의 내적.

    공통 키를 dict view 교집합(C 레벨)으로 먼저 구한다. 대부분의 쌍은 겹치는 n-gram이
    몇 개뿐이라, 짧은 쪽 전체를 훑으며 get 하는 것보다 훨씬 싸다.
    """
    shared = a.keys() & b.keys()
    if not shared:
        return 0.0
    return sum(a[g] * b[g] for g in shared)


# ── MinHash LSH (근사 중복) ───────────────────────────────────────────────────

def _perm_params(perms: int) -> list[tuple[int, int]]:
    """결정적 순열 계수. 시드 고정이라 실행 간 결과가 흔들리지 않는다."""
    params: list[tuple[int, int]] = []
    for i in range(perms):
        a = (2 * i + 1) * 0x9E3779B1 % _MERSENNE or 1
        b = (i + 1) * 0x85EBCA77 % _MERSENNE
        params.append((a, b))
    return params


_PERMS = _perm_params(MINHASH_PERMS)


def _minhash(grams: set[str]) -> tuple[int, ...]:
    if not grams:
        return tuple([_MERSENNE] * MINHASH_PERMS)
    base = [zlib.crc32(g.encode("utf-8")) for g in grams]
    return tuple(min((a * h + b) % _MERSENNE for h in base) for a, b in _PERMS)


def _lsh_candidates(variants: list[_Variant]) -> set[tuple[int, int]]:
    rows = MINHASH_PERMS // MINHASH_BANDS
    signatures = [_minhash(v.grams) for v in variants]
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    for i, sig in enumerate(signatures):
        for band in range(MINHASH_BANDS):
            key = (band, sig[band * rows : (band + 1) * rows])
            buckets[key].append(i)

    pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) < 2 or len(members) > 200:
            continue
        for i_pos, i in enumerate(members):
            for j in members[i_pos + 1 :]:
                pairs.add((i, j) if i < j else (j, i))
    return pairs


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / (len(a) + len(b) - inter)


# ── 역색인 블로킹 (유사 의견) ─────────────────────────────────────────────────

def _blocking_candidates(variants: list[_Variant], subset: list[int] | None = None) -> set[tuple[int, int]]:
    """각 변형의 고가중치 n-gram만 역색인으로 묶어 후보쌍을 만든다."""
    indices = subset if subset is not None else [v.index for v in variants]
    by_index = {v.index: v for v in variants}

    postings: dict[str, list[int]] = defaultdict(list)
    for idx in indices:
        vec = by_index[idx].vec
        top = sorted(vec.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERMS_PER_DOC]
        for gram, _ in top:
            postings[gram].append(idx)

    pairs: set[tuple[int, int]] = set()
    for members in postings.values():
        if len(members) < 2 or len(members) > MAX_POSTINGS:
            continue
        for i_pos, i in enumerate(members):
            for j in members[i_pos + 1 :]:
                pairs.add((i, j) if i < j else (j, i))
    return pairs


# ── 군집화 ────────────────────────────────────────────────────────────────────

def _components(edges: list[tuple[int, int]], indices: list[int]) -> list[list[int]]:
    pos = {idx: i for i, idx in enumerate(indices)}
    uf = _UnionFind(len(indices))
    for a, b in edges:
        uf.union(pos[a], pos[b])
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in indices:
        groups[uf.find(pos[idx])].append(idx)
    return [sorted(g) for g in groups.values()]


def _cohesion(variants: dict[int, _Variant], indices: list[int]) -> float:
    """군집 내부 평균 코사인(대표 변형 표본 기준). 단일 변형이면 1.0."""
    sample = _sample_indices(indices, MEDOID_SAMPLE)
    if len(sample) < 2:
        return 1.0
    total = 0.0
    count = 0
    for i_pos, i in enumerate(sample):
        for j in sample[i_pos + 1 :]:
            total += _cosine(variants[i].vec, variants[j].vec)
            count += 1
    return total / count if count else 1.0


def _sample_indices(indices: list[int], limit: int) -> list[int]:
    """결정적 균등 표본 — 난수를 쓰지 않아 실행 간 결과가 같다."""
    if len(indices) <= limit:
        return list(indices)
    step = len(indices) / limit
    return [indices[int(i * step)] for i in range(limit)]


def _split_component(
    variants: dict[int, _Variant],
    indices: list[int],
    threshold: float,
    rounds_left: int,
    total_weight: int,
) -> list[list[int]]:
    """큰데 응집도 낮은 군집만 임계값을 올려 재분할한다."""
    weight = sum(variants[i].weight for i in indices)
    share = weight / total_weight if total_weight else 0.0
    if (
        rounds_left <= 0
        or len(indices) < 3
        or share <= SPLIT_MAX_SHARE
        or _cohesion(variants, indices) >= SPLIT_MIN_COHESION
    ):
        return [indices]

    higher = min(threshold + SPLIT_STEP, 0.95)
    vlist = [variants[i] for i in indices]
    edges = [
        (a, b)
        for a, b in sorted(_blocking_candidates(vlist, indices))
        if _cosine(variants[a].vec, variants[b].vec) >= higher
    ]
    parts = _components(edges, indices)
    if len(parts) <= 1:
        return [indices]

    out: list[list[int]] = []
    for part in parts:
        out.extend(_split_component(variants, part, higher, rounds_left - 1, total_weight))
    return out


def _top_terms(
    variants: dict[int, _Variant],
    indices: list[int],
    word_df: Counter[str],
    doc_count: int,
    limit: int = 8,
) -> list[str]:
    """사람이 읽는 키워드. 문자 n-gram이 아니라 조사 뗀 단어·bigram으로 뽑는다."""
    scores: dict[str, float] = defaultdict(float)
    for idx in _sample_indices(indices, MEDOID_SAMPLE):
        v = variants[idx]
        for term in set(word_terms_with_bigrams(v.text)):
            idf = math.log((doc_count + 1) / (word_df[term] + 1)) + 1.0
            scores[term] += v.weight * idf

    # 인접 bigram은 서로 한 단어씩 겹쳐 "1세대 1주택자 / 1주택자 종합부동산세 / …"처럼
    # 같은 문장을 잘라 늘어놓기 쉽다. 이미 쓴 단어가 들어간 후보는 건너뛰어,
    # 키워드 목록이 서로 다른 이야기를 하도록 만든다.
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    picked: list[str] = []
    used: set[str] = set()
    for term, _ in ranked:
        tokens = set(term.split())
        if tokens & used:
            continue
        picked.append(term)
        used |= tokens
        if len(picked) >= limit:
            break
    return picked


def _medoid(variants: dict[int, _Variant], indices: list[int]) -> int:
    """군집 내 다른 의견들과 가장 가까운(= 가장 대표적인) 변형."""
    if len(indices) == 1:
        return indices[0]
    sample = _sample_indices(indices, MEDOID_SAMPLE)
    best_idx = sample[0]
    best_score = -1.0
    for i in sample:
        score = sum(
            variants[j].weight * _cosine(variants[i].vec, variants[j].vec)
            for j in sample
            if j != i
        )
        # 같은 점수면 건수 많은 쪽 → 그래도 같으면 id 사전순 (결정적 tie-break)
        key = (score, variants[i].weight, variants[i].rep_id)
        best_key = (best_score, variants[best_idx].weight, variants[best_idx].rep_id)
        if best_score < 0 or key > best_key:
            best_idx, best_score = i, score
    return best_idx


def cluster_opinions(
    docs: list[OpinionDoc],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
    collect_borderline: int = 0,
) -> ClusterResult:
    """의견 목록을 유사 내용끼리 묶어 건수 내림차순 군집으로 돌려준다."""
    docs = [d for d in docs if d.text and d.text.strip()]
    if not docs:
        return ClusterResult(clusters=[], total=0, unique_texts=0, threshold=threshold)

    variants, empties = _build_variants(docs)
    _build_vectors(variants)
    by_index = {v.index: v for v in variants}
    indices = [v.index for v in variants]
    total_weight = sum(v.weight for v in variants)

    borderline: list[tuple[str, str, float]] = []
    edges: list[tuple[int, int]] = []
    scored: set[tuple[int, int]] = set()

    # 2단계: 근사 중복
    for a, b in sorted(_lsh_candidates(variants)):
        if _jaccard(by_index[a].grams, by_index[b].grams) >= dup_threshold:
            edges.append((a, b))
            scored.add((a, b))

    # 3단계: 유사 의견
    low, high = threshold - 0.10, threshold + 0.10
    for a, b in sorted(_blocking_candidates(variants)):
        if (a, b) in scored:
            continue
        sim = _cosine(by_index[a].vec, by_index[b].vec)
        if sim >= threshold:
            edges.append((a, b))
        elif collect_borderline and low <= sim < high and len(borderline) < collect_borderline:
            borderline.append((by_index[a].rep_id, by_index[b].rep_id, round(sim, 3)))

    groups: list[list[int]] = []
    for comp in _components(edges, indices):
        groups.extend(_split_component(by_index, comp, threshold, SPLIT_ROUNDS, total_weight))

    # 키워드용 단어 df (변형 기준)
    word_df: Counter[str] = Counter()
    for v in variants:
        word_df.update(set(word_terms_with_bigrams(v.text)))

    clusters: list[Cluster] = []
    for group in groups:
        member_ids = sorted(mid for idx in group for mid in by_index[idx].member_ids)
        medoid_idx = _medoid(by_index, group)
        exemplars = [
            by_index[i].rep_id
            for i in sorted(group, key=lambda i: (-by_index[i].weight, by_index[i].rep_id))[:3]
        ]
        clusters.append(
            Cluster(
                cluster_id=0,
                size=len(member_ids),
                member_ids=member_ids,
                medoid_id=by_index[medoid_idx].rep_id,
                medoid_text=by_index[medoid_idx].text,
                exemplar_ids=exemplars,
                top_terms=_top_terms(by_index, group, word_df, len(variants)),
                cohesion=round(_cohesion(by_index, group), 3),
                variant_count=len(group),
                exact_dup_max=max(by_index[i].weight for i in group),
            )
        )

    if empties:
        ids = sorted(d.doc_id for d in empties)
        clusters.append(
            Cluster(
                cluster_id=0,
                size=len(ids),
                member_ids=ids,
                medoid_id=ids[0],
                medoid_text=next(d.text for d in empties if d.doc_id == ids[0]),
                exemplar_ids=ids[:3],
                top_terms=[],
                cohesion=1.0,
                variant_count=1,
                exact_dup_max=len(ids),
            )
        )

    clusters.sort(key=lambda c: (-c.size, c.medoid_id))
    for rank, cluster in enumerate(clusters, start=1):
        cluster.cluster_id = rank

    return ClusterResult(
        clusters=clusters,
        total=len(docs),
        unique_texts=len(variants) + (1 if empties else 0),
        threshold=threshold,
        borderline_pairs=borderline,
    )

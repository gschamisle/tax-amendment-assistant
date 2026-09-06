"""입법예고 의견 텍스트 정규화 — 유사도 계산 전처리.

의견은 형식이 자유롭다. 같은 말을 하는 두 의견이 띄어쓰기·이모지·인사말 때문에
다른 의견으로 갈리면 군집화가 무너지므로, 유사도를 재기 전에 다음을 맞춘다:

  1. norm_text        — NFKC·제어문자·반복문자·구두점·공백 정규화
  2. split_sentences  — 문장 분리(한국어 종결어미 + 구두점 + 줄바꿈)
  3. boilerplate_sentences / strip_boilerplate
                      — "존경하는 위원님께", "감사합니다" 같은 상투구 제거
  4. char_ngrams      — 공백 제거 후 문자 n-gram (조사 변형·띄어쓰기 흔들림에 강함)
  5. word_terms       — 조사를 떼어낸 단어 토큰 (사람이 읽는 키워드용)

상투구 제거는 **본문을 지우면 안 된다**는 제약이 가장 중요하다. 복붙 의견이 코퍼스의
절반을 차지하는 게 정상이라, 단순히 "자주 나오는 문장"을 지우면 정작 핵심 주장이
사라진다. 그래서 실질 신호(숫자·조문 인용·주장 어휘)가 있는 문장은 df가 아무리 높아도
상투구로 보지 않고, 제거 결과가 빈 문자열이면 원문을 그대로 돌려준다.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# ── 정규화 ────────────────────────────────────────────────────────────────────

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAG_RE = re.compile(r"<[^>]{1,200}>")
_REPEAT_RE = re.compile(r"(.)\1{2,}")
# %는 남긴다 — 세법 의견에서 '60%', '3%'는 그 자체가 핵심 주장이다.
# 완성형 한글·숫자·영문·%만 남는다. NFKC가 호환 자모(ㅋ, ㅠ)를 조합용 자모로 바꾸므로
# 'ㅋㅋㅋ', 'ㅠㅠ' 같은 감탄 표기는 여기서 함께 떨어져 나간다(유사도에 잡음만 준다).
_KEEP_RE = re.compile(r"[^0-9a-z가-힣%\s]")
_WS_RE = re.compile(r"\s+")

# 문장 분리: 종결 구두점 / 줄바꿈 / 한국어 종결어미 뒤
_SENT_SPLIT_RE = re.compile(
    r"(?<=[.!?。])\s+"
    r"|[\r\n]+"
    r"|(?<=니다)\s+(?=[가-힣])"
    r"|(?<=합니다)\s*(?=[가-힣])"
    r"|(?<=습니다)\s*(?=[가-힣])"
)

# ── 상투구 ────────────────────────────────────────────────────────────────────
# 의견 앞뒤에 붙는 인사·맺음말. 정규화된 문장 기준으로 매칭한다.
GREETING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^안녕(하세요|하십니까|하십니까요)?$",
        r"^존경하[는던].{0,20}$",
        r"^수고(하십니다|많으십니다|많습니다).{0,10}$",
        r"^감사합니다.{0,10}$",
        r"^고맙습니다.{0,10}$",
        r"^이상입니다.{0,10}$",
        r"^(잘\s*)?부탁(드립니다|합니다).{0,10}$",
        r"^(적극\s*)?검토(를)?\s*(부탁|바랍)(드립니다|니다|합니다).{0,10}$",
        r"^국민의?\s*한\s*사람으로서.{0,20}$",
        r"^의견\s*(제출|드립니다|올립니다).{0,10}$",
    )
)

# 실질 신호 어휘 — 이 어휘가 들어간 문장은 df가 높아도 상투구로 보지 않는다.
_SUBSTANTIVE_WORDS: tuple[str, ...] = (
    "폐지", "인하", "인상", "완화", "강화", "반대", "찬성", "유예", "개정", "신설",
    "삭제", "과세", "면제", "공제", "세율", "세금", "부담", "기준", "적용", "제외",
    "확대", "축소", "환원", "철회", "도입", "유지", "상향", "하향",
)
_ARTICLE_HINT_RE = re.compile(r"제?\s*\d+\s*조|\d+\s*%|\d+\s*억|\d+\s*만원")


# 세법 의견에 흔한 약칭 → 정식 명칭. "종부세 폐지"와 "종합부동산세 폐지"가 다른
# 의견으로 갈리는 것을 막는다. 표면형이 달라도 같은 말이면 같은 군집이어야 한다.
ABBREVIATIONS: dict[str, str] = {
    "종부세": "종합부동산세",
    "종소세": "종합소득세",
    "양도세": "양도소득세",
    "근소세": "근로소득세",
    "금투세": "금융투자소득세",
    "상증세": "상속세및증여세",
    "부가세": "부가가치세",
    "재산세와 종부세": "재산세와 종합부동산세",
    "1가구1주택": "1세대1주택",
    "1가구 1주택": "1세대 1주택",
    "일가구일주택": "1세대1주택",
    "일세대일주택": "1세대1주택",
    "공시가 ": "공시가격 ",
}
_ABBREV_RE = re.compile("|".join(sorted((re.escape(k) for k in ABBREVIATIONS), key=len, reverse=True)))


def expand_abbreviations(text: str) -> str:
    return _ABBREV_RE.sub(lambda m: ABBREVIATIONS[m.group(0)], text)


def norm_text(text: str) -> str:
    """유사도 비교용 정규화 문자열.

    NFKC → 소문자 → HTML 태그·제어문자 제거 → 3회 이상 반복 문자 축약 →
    한글/영문/숫자/%/공백만 남김 → 세법 약칭 통일 → 공백 축약.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).lower()
    s = _TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = _CONTROL_RE.sub(" ", s)
    s = _REPEAT_RE.sub(r"\1\1", s)
    s = _KEEP_RE.sub(" ", s)
    s = expand_abbreviations(s)
    return _WS_RE.sub(" ", s).strip()


def split_sentences(text: str) -> list[str]:
    """의견 본문을 문장 단위로 나눈다(정규화 전 원문 기준)."""
    if not text:
        return []
    raw = unicodedata.normalize("NFKC", str(text))
    raw = _TAG_RE.sub("\n", raw)
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(raw) if p and p.strip()]
    return [p for p in parts if norm_text(p)]


def _is_substantive(norm_sentence: str) -> bool:
    """상투구 후보에서 제외해야 하는(실질 내용이 있는) 문장인가."""
    if _ARTICLE_HINT_RE.search(norm_sentence):
        return True
    return any(w in norm_sentence for w in _SUBSTANTIVE_WORDS)


def _is_greeting(norm_sentence: str) -> bool:
    return any(p.match(norm_sentence) for p in GREETING_PATTERNS)


def boilerplate_sentences(
    docs: list[str],
    *,
    min_df_ratio: float = 0.20,
    min_docs: int = 5,
    max_chars: int = 40,
) -> set[str]:
    """코퍼스 전체에서 상투구로 볼 문장(정규화형)의 집합.

    curated 인사말 패턴 + "짧고, 실질 신호가 없고, 문서 다수에 등장하는 문장".
    실질 신호가 있는 문장은 아무리 자주 나와도 포함하지 않는다 — 복붙 의견의
    핵심 주장을 지워버리는 사고를 막는 안전장치다.
    """
    per_doc: list[set[str]] = []
    for doc in docs:
        norms = {norm_text(s) for s in split_sentences(doc)}
        per_doc.append({n for n in norms if n})

    df: Counter[str] = Counter()
    for norms in per_doc:
        df.update(norms)

    total = len(per_doc)
    threshold = max(min_docs, int(total * min_df_ratio)) if total else min_docs

    boiler: set[str] = set()
    for sent, count in df.items():
        if _is_greeting(sent):
            boiler.add(sent)
            continue
        if len(sent) > max_chars or _is_substantive(sent):
            continue
        if count >= threshold:
            boiler.add(sent)
    return boiler


def strip_boilerplate(text: str, boiler: set[str]) -> str:
    """상투구 문장을 제거한 본문. 전부 지워지면 원문을 그대로 돌려준다."""
    if not text:
        return ""
    kept = [s for s in split_sentences(text) if norm_text(s) not in boiler]
    if not kept:
        return text
    return " ".join(kept)


# ── 자질 추출 ─────────────────────────────────────────────────────────────────

def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    """공백을 없앤 정규화 문자열의 문자 n-gram 빈도.

    한국어는 조사·띄어쓰기가 흔들려도 어간이 이어지므로 문자 n-gram이
    형태소 분석기 없이도 유사도 신호를 잘 잡는다.
    """
    s = norm_text(text).replace(" ", "")
    if not s:
        return Counter()
    if len(s) <= n:
        return Counter([s])
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


# 조사만 떼어낸다. 종결어미(-하라, -합니다)는 주장 성격을 담고 있어 남긴다.
_JOSA: tuple[str, ...] = (
    "에서는", "에게는", "으로는", "이라도", "에서도", "에게도", "까지도",
    "에서", "에게", "으로", "라도", "이나", "부터", "까지", "처럼", "보다",
    "마저", "조차", "이란", "라는", "이는", "과의", "와의", "의는",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "와", "과", "나",
)


def strip_josa(word: str) -> str:
    """단어 끝의 조사를 1회 제거한다(어간이 2자 이상 남을 때만)."""
    for josa in _JOSA:
        if word.endswith(josa) and len(word) - len(josa) >= 2:
            return word[: -len(josa)]
    return word


_STOPWORDS: frozenset[str] = frozenset(
    {
        "그리고", "그러나", "하지만", "또한", "그런데", "따라서", "그래서", "때문",
        "있습니다", "없습니다", "합니다", "입니다", "됩니다", "생각", "의견", "경우",
        "것을", "것이", "것은", "저는", "제가", "우리", "이런", "저런", "그런", "매우",
        "정말", "너무", "너무나", "정도", "관련", "대한", "대해", "위해", "통해",
    }
)


def word_terms(text: str, *, min_len: int = 2) -> list[str]:
    """사람이 읽을 수 있는 키워드 토큰 (조사 제거 + 불용어 제거)."""
    terms: list[str] = []
    for raw in norm_text(text).split():
        word = strip_josa(raw)
        if len(word) < min_len or word in _STOPWORDS or word.isdigit():
            continue
        terms.append(word)
    return terms


def word_terms_with_bigrams(text: str, *, min_len: int = 2) -> list[str]:
    """단어 토큰 + 인접 단어 bigram (예: '공정시장가액비율 인하')."""
    unigrams = word_terms(text, min_len=min_len)
    bigrams = [f"{a} {b}" for a, b in zip(unigrams, unigrams[1:])]
    return unigrams + bigrams

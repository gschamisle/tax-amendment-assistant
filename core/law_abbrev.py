"""법령명·조문 표기 약칭 — 도표에 쓰기 위한 짧은 이름.

'소득세법 시행령 제73조의2'는 도표 라벨로 너무 길다. 노드 하나가 15자를 넘으면
겹치거나 잘리고, 잘린 라벨은 '소득세법 시행…'처럼 어느 법인지도 안 남는다.
실무 표기를 그대로 쓴다:

    소득세법 시행령 제73조의2   →  소득령 §73의2
    부가가치세법 시행규칙        →  부가칙
    국제조세조정에 관한 법률     →  국조법

**규칙 유추가 아니라 표로 둔다.** '국제조세조정에 관한 법률 → 국조'는 어떤
자동 규칙으로도 안 나온다(첫 글자 조합도, 어절 축약도 아니다). 세법 실무의
관용 약칭이라 사람이 정해야 하고, 표에 없으면 원문을 그대로 돌려준다 —
틀린 약칭을 지어내느니 긴 이름이 낫다.
"""
from __future__ import annotations

import re

# 모법 어간. 뒤에 법/령/칙을 붙여 완성한다.
_STEMS: dict[str, str] = {
    "관세법": "관세",
    "국세기본법": "국기",
    "국세징수법": "국징",
    "국제조세조정에 관한 법률": "국조",
    "농어촌특별세법": "농특",
    "법인세법": "법인",
    "부가가치세법": "부가",
    "상속세 및 증여세법": "상증",
    "소득세법": "소득",
    "조세특례제한법": "조특",
    "종합부동산세법": "종부",
    # 추적 밖이지만 인용에 자주 나오는 법령
    "지방세법": "지방세",
    "지방세특례제한법": "지특",
    "국세기본법": "국기",
    "자본시장과 금융투자업에 관한 법률": "자본시장법",
    "민간임대주택에 관한 특별법": "민임법",
    "주택법": "주택법",
    "헌법": "헌법",
}
_SUFFIX: tuple[tuple[str, str], ...] = (
    ("시행규칙", "칙"),
    ("시행령", "령"),
)

_JO_RE = re.compile(r"^제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(.*)$")


def law(name: str) -> str:
    """법령명 → 약칭. 표에 없으면 원문 그대로."""
    text = str(name).strip()
    if not text:
        return ""
    for suffix, mark in _SUFFIX:
        if text.endswith(suffix):
            stem = _STEMS.get(text[: -len(suffix)].strip())
            return f"{stem}{mark}" if stem else text
    stem = _STEMS.get(text)
    if not stem:
        return text
    return stem if stem.endswith(("법", "칙", "령")) else f"{stem}법"


def is_known(name: str) -> bool:
    """약칭 표에 있는 법령인지. '관세법'처럼 약칭이 원문과 같은 경우가 있어
    `law(x) == x` 로는 미등록 여부를 판정할 수 없다."""
    text = str(name).strip()
    for suffix, _mark in _SUFFIX:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip() in _STEMS
    return text in _STEMS


def article(ref: str) -> str:
    """'제73조의2제1항' → '§73의2제1항'. 조문 표기가 아니면 원문 그대로."""
    m = _JO_RE.match(str(ref).strip())
    if not m:
        return str(ref).strip()
    tail = (m.group(3) or "").strip()
    return f"§{m.group(1)}" + (f"의{m.group(2)}" if m.group(2) else "") + tail


def jo_key(key: str) -> str:
    """'73의2' → '§73의2'. 그래프 내부 키 표기용."""
    parts = str(key).split("의")
    if not parts[0].isdigit():
        return str(key)
    return f"§{parts[0]}" + (f"의{parts[1]}" if len(parts) > 1 else "")


def full(law_name: str, ref: str = "") -> str:
    """'소득세법 시행령', '제73조의2' → '소득령 §73의2'."""
    left = law(law_name)
    right = article(ref) if ref else ""
    return f"{left} {right}".strip()

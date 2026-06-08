"""개정 요강 자유 형식 → 구조화된 개정 의도."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from openai import OpenAI

from config import OPENAI_API_KEY

_HANG_SYMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


@dataclass
class TextReplacement:
    old_text: str
    new_text: str
    hangs: list[str] = field(default_factory=list)


@dataclass
class OutlineIntent:
    target_hangs: list[str]
    replacements: list[TextReplacement]
    summary: str
    source: str  # regex | gpt | heuristic | none
    target_ho: str = ""
    target_mok: str = ""

    @property
    def amendment_level(self) -> str:
        if self.target_mok:
            return "mok"
        if self.target_ho:
            return "ho"
        return "hang"

    @property
    def primary_hang(self) -> str:
        if self.target_hangs:
            return self.target_hangs[0]
        for rep in self.replacements:
            if rep.hangs:
                return rep.hangs[0]
        return ""

    @property
    def primary_replacement(self) -> TextReplacement | None:
        hang = self.primary_hang
        for rep in self.replacements:
            if not hang or hang in rep.hangs or not rep.hangs:
                return rep
        return self.replacements[0] if self.replacements else None


def _extract_ho_mok(outline: str) -> tuple[str, str, list[str]]:
    """요강에서 호·목 번호 추출. (호, 목, 항목록)"""
    hangs = _extract_target_hangs(outline)
    ho = ""
    mok = ""

    m = re.search(r"제(\d+)항제(\d+)호(?:제?([가-힣])\.?\s*목)?", outline)
    if m:
        if not hangs:
            hangs = [m.group(1)]
        ho = m.group(2)
        if m.group(3):
            mok = m.group(3)
        return ho, mok, hangs

    m = re.search(r"제(\d+)호(?:제?([가-힣])\.?\s*목)?", outline)
    if m:
        ho = m.group(1)
        if m.group(2):
            mok = m.group(2)
        return ho, mok, hangs

    m = re.search(r"(?<!\d)(\d+)호(?:\s*([가-힣])\.?\s*목)?", outline)
    if m:
        ho = m.group(1)
        if m.group(2):
            mok = m.group(2)
    return ho, mok, hangs


def _extract_target_hangs(outline: str) -> list[str]:
    hangs: list[str] = []
    for m in re.finditer(r"제(\d+)항|(?<![제\d])(\d+)항", outline):
        num = m.group(1) or m.group(2)
        if num and num not in hangs:
            hangs.append(num)
    for sym in _HANG_SYMS:
        if sym in outline:
            num = str(_HANG_SYMS.index(sym) + 1)
            if num not in hangs:
                hangs.append(num)
    return hangs


def _normalize_manwon(text: str) -> int | None:
    t = text.strip().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"([0-9]+)만원", t)
    if m:
        return int(m.group(1))
    aliases = {
        "천만원": 1000,
        "1000만원": 1000,
        "팔백만원": 800,
        "800만원": 800,
    }
    return aliases.get(t.replace(",", ""))


def _format_manwon_from_int(n: int) -> str:
    return f"{n:,}만원"


def _extract_new_amount_text(outline: str) -> str:
    m = re.search(r"([0-9,]+)\s*[→\-]\s*([0-9,]+)\s*만원", outline)
    if m:
        return _format_manwon_from_int(int(m.group(2).replace(",", "")))
    for word, n in (("천만원", 1000),):
        if word in outline.replace(" ", ""):
            return _format_manwon_from_int(n)
    return ""


def _hang_block_content(article_text: str, hang: str) -> str:
    sym = hang_to_sym(hang)
    if not sym:
        return ""
    in_block = False
    lines: list[str] = []
    for line in article_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(sym):
            in_block = True
            lines.append(line)
            continue
        if in_block:
            if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]", stripped):
                break
            lines.append(line)
    return "\n".join(lines)


def _heuristic_intent(outline: str, article_text: str) -> OutlineIntent | None:
    """조문 본문 + 구어체 요강에서 금액 상·하향을 추론 (GPT/regex 실패 시)."""
    hangs = _extract_target_hangs(outline)
    new_text = _extract_new_amount_text(outline)
    new_val = _normalize_manwon(new_text) if new_text else None
    if not hangs or not new_val:
        return None
    if not re.search(r"상향|인상|올리|증액|확대|높이|늘리", outline):
        return None

    hang = hangs[0]
    block = _hang_block_content(article_text, hang)
    if not block:
        return None
    candidates = re.findall(r"[0-9,]+만원", block)
    if not candidates:
        return None
    old_text = ""
    for cand in candidates:
        val = _normalize_manwon(cand)
        if val and val != new_val:
            old_text = cand
            break
    if not old_text or old_text not in article_text:
        return None
    new_fmt = _format_manwon_from_int(new_val)
    ho, mok, _ = _extract_ho_mok(outline)
    return OutlineIntent(
        target_hangs=[hang],
        replacements=[TextReplacement(old_text=old_text, new_text=new_fmt, hangs=[hang])],
        summary=f"제{hang}항 {old_text}→{new_fmt} (요강·조문 대조)",
        source="heuristic",
        target_ho=ho,
        target_mok=mok,
    )


def _percent_to_bunmu(text: str) -> str:
    """3% → 100분의 3 (법령 본문 표기)."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)%", text.strip())
    if not m:
        return ""
    val = float(m.group(1))
    if abs(val - round(val)) < 0.000001:
        return f"100분의 {int(round(val))}"
    return ""


def _resolve_text_pair(old_text: str, new_text: str, article_text: str) -> tuple[str, str]:
    """요강의 % 표기를 조문 본문의 100분의 N 표기에 맞춘다."""
    if old_text in article_text:
        resolved_new = new_text
        if new_text not in article_text:
            bun_new = _percent_to_bunmu(new_text)
            if bun_new:
                resolved_new = bun_new
        return old_text, resolved_new

    bun_old = _percent_to_bunmu(old_text)
    bun_new = _percent_to_bunmu(new_text)
    if bun_old and bun_old in article_text:
        return bun_old, bun_new or new_text
    return old_text, new_text


def _extract_old_new_regex(outline: str) -> tuple[str, str] | None:
    patterns = [
        r"['\"]([^'\"]+)['\"]\s*을\s*['\"]([^'\"]+)['\"]\s*(?:으로|로)",
        r"([0-9,]+(?:\.\d+)?%?|[0-9,]+만원|[0-9,]+원)\s*을\s*([0-9,]+(?:\.\d+)?%?|[0-9,]+만원|[0-9,]+원)\s*(?:으로|로)",
        r"([0-9,]+만원)\s*에서\s*([0-9,]+만원)\s*(?:으로|로)",
        r"현행\s*['\"]?([^'\"\s]+?)['\"]?에서\s*['\"]?([^'\"\s]+?)['\"]?(?:으로|로)",
    ]
    for pattern in patterns:
        m = re.search(pattern, outline)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None


def _try_regex_intent(outline: str, article_text: str = "") -> OutlineIntent | None:
    ho, mok, hangs = _extract_ho_mok(outline)
    pair = _extract_old_new_regex(outline)
    if not pair:
        return None
    old_text, new_text = _resolve_text_pair(pair[0], pair[1], article_text)
    if article_text and old_text not in article_text:
        return None
    rep = TextReplacement(old_text=old_text, new_text=new_text, hangs=hangs)
    loc = ""
    if hangs:
        loc = f"제{hangs[0]}항"
        if ho:
            loc += f"제{ho}호"
        if mok:
            loc += f"제{mok}목"
        loc += " "
    return OutlineIntent(
        target_hangs=hangs,
        replacements=[rep],
        summary=f"{loc}{old_text}→{new_text}",
        source="regex",
        target_ho=ho,
        target_mok=mok,
    )


_INTENT_SYSTEM = """당신은 대한민국 법령 개정 요강 해석기입니다.
사용자는 구어체·메모·불완전한 문장으로 개정 의도를 적습니다. [현행 조문]을 읽고 실제로 무엇을 어떻게 바꾸려는지 구조화하세요.

예시 입력 → 해석:
- "제3항 800만원을 1,000만원으로 상향" → 제3항 한도 800만원을 1,000만원으로
- "③ 한도 천만원으로 올림" → 조문에 800만원이 있으면 800만원→1,000만원
- "손금불산입 요건 완화" → replacements 없음, summary만

JSON만 반환:
{
  "summary": "한 줄 의도",
  "target_hangs": ["3"],
  "replacements": [{"old_text": "800만원", "new_text": "1,000만원", "hangs": ["3"]}]
}

규칙:
- old_text는 반드시 [현행 조문]에 그대로 존재하는 연속 문자열.
- 숫자·문구 치환이 불명확하거나 신설·삭제·전면 개정이면 replacements는 [].
- target_hangs는 항 번호만 ("3", "5의2" 아님 — 항이면 "3").
- hangs는 치환 적용 항 번호. 비우면 target_hangs와 동일하게 간주."""


def _gpt_parse_intent(outline: str, article_text: str, api_key: str) -> OutlineIntent | None:
    key = api_key or OPENAI_API_KEY
    if not key:
        return None
    client = OpenAI(api_key=key)
    user = f"""[현행 조문]
{article_text}

[개정 요강 (자유 형식)]
{outline}"""
    try:
        resp = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception:
        data = None

    if not data:
        return None

    hangs = [str(h) for h in data.get("target_hangs", []) if str(h).strip()]
    reps: list[TextReplacement] = []
    for item in data.get("replacements", []):
        old_t = str(item.get("old_text", "")).strip()
        new_t = str(item.get("new_text", "")).strip()
        if not old_t or not new_t:
            continue
        old_t, new_t = _resolve_text_pair(old_t, new_t, article_text)
        if old_t not in article_text:
            continue
        rep_hangs = [str(h) for h in item.get("hangs", []) if str(h).strip()] or hangs
        reps.append(TextReplacement(old_text=old_t, new_text=new_t, hangs=rep_hangs))

    summary = str(data.get("summary", "")).strip() or outline.strip()
    if not hangs and reps:
        hangs = reps[0].hangs[:]
    if not hangs and not reps:
        ho, mok, _ = _extract_ho_mok(outline)
        return OutlineIntent([], [], summary, "gpt", target_ho=ho, target_mok=mok)

    ho, mok, regex_hangs = _extract_ho_mok(outline)
    if not hangs and regex_hangs:
        hangs = regex_hangs
    return OutlineIntent(
        target_hangs=hangs,
        replacements=reps,
        summary=summary,
        source="gpt",
        target_ho=ho,
        target_mok=mok,
    )


def parse_outline_intent(
    outline: str,
    article: dict,
    api_key: str = "",
    *,
    prefer_gpt: bool = True,
) -> OutlineIntent:
    """요강 의도 구조화. regex는 빠른 경로, 실패·불완전 시 GPT."""
    outline = outline.strip()
    article_text = str(article.get("내용", ""))
    if not outline:
        return OutlineIntent([], [], "", "none", target_ho="", target_mok="")

    regex_intent = _try_regex_intent(outline, article_text)
    if not prefer_gpt:
        if regex_intent:
            return regex_intent
        heuristic = _heuristic_intent(outline, article_text)
        if heuristic:
            return heuristic
        hangs = _extract_target_hangs(outline)
        ho, mok, hangs = _extract_ho_mok(outline)
        return OutlineIntent(hangs, [], outline, "none", target_ho=ho, target_mok=mok)

    gpt_intent = _gpt_parse_intent(outline, article_text, api_key)
    if gpt_intent and (gpt_intent.replacements or gpt_intent.target_hangs):
        if regex_intent and regex_intent.replacements and not gpt_intent.replacements:
            gpt_intent.replacements = regex_intent.replacements
        if regex_intent and regex_intent.target_hangs and not gpt_intent.target_hangs:
            gpt_intent.target_hangs = regex_intent.target_hangs
        return gpt_intent

    heuristic = _heuristic_intent(outline, article_text)
    if heuristic:
        return heuristic

    if regex_intent:
        return regex_intent

    if gpt_intent:
        return gpt_intent

    ho, mok, hangs = _extract_ho_mok(outline)
    return OutlineIntent(hangs, [], outline, "none", target_ho=ho, target_mok=mok)


def hang_to_sym(hang: str) -> str:
    try:
        return _HANG_SYMS[int(hang) - 1]
    except (ValueError, IndexError):
        return ""

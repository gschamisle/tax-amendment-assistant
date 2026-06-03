"""현행·개정안 조문 표시 (항 압축, 호·목 개정 시 상위 전문·대시)."""
from __future__ import annotations

import re

from core.hwpx_writer import _process_kajeong_an
from core.outline_intent import OutlineIntent, hang_to_sym

_HANG_SYM_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
_HO_LINE_RE = re.compile(r"^(\d+)\.\s")
_MOK_LINE_RE = re.compile(r"^([가-힣])\.\s")
_HAS_U_RE = re.compile(r"<u>")


def format_compressed_hang_label(symbols: list[str], suffix: str) -> str:
    """연속 미변경 항: 2개 ①·②, 3개 이상 ①~④."""
    if not symbols:
        return ""
    if len(symbols) == 1:
        return f"{symbols[0]} {suffix}"
    if len(symbols) == 2:
        return f"{symbols[0]}·{symbols[1]} {suffix}"
    return f"{symbols[0]}~{symbols[-1]} {suffix}"


def compress_unchanged_hang_lines(lines: list[str], *, amended: bool) -> list[str]:
    """연속 (생략)/(현행과같음) 항을 · / ~ 형식으로 묶는다."""
    suffix = "(현행과같음)" if amended else "(생략)"
    compressed_re = re.compile(
        rf"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])(?:·~?[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳~·]*)?\s*{re.escape(suffix)}$"
    )

    def is_omit_line(line: str) -> bool:
        s = line.strip()
        if suffix not in s:
            return False
        if amended and _HAS_U_RE.search(s):
            return False
        if not amended and "<del>" in s:
            return False
        if compressed_re.match(s):
            return True
        m = _HANG_SYM_RE.match(s)
        return bool(m and (s.endswith(suffix) or f" {suffix}" in s))

    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not is_omit_line(line):
            result.append(line)
            i += 1
            continue
        syms: list[str] = []
        while i < len(lines) and is_omit_line(lines[i]):
            m = _HANG_SYM_RE.match(lines[i].strip())
            if m:
                syms.append(m.group(1))
            i += 1
        if syms:
            result.append(format_compressed_hang_label(syms, suffix))
        else:
            result.append(line)
            i += 1
    return result


def split_hang_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []
    sym = ""
    for line in text.splitlines():
        m = _HANG_SYM_RE.match(line.lstrip())
        if m and buf:
            blocks.append((sym, "\n".join(buf)))
            sym = m.group(1)
            buf = [line]
        elif m:
            sym = m.group(1)
            buf = [line]
        else:
            buf.append(line)
    if buf:
        blocks.append((sym, "\n".join(buf)))
    return blocks


def _line_matches_ho(line: str, ho: str) -> bool:
    m = _HO_LINE_RE.match(line.lstrip())
    return bool(ho and m and m.group(1) == ho)


def _line_matches_mok(line: str, mok: str) -> bool:
    m = _MOK_LINE_RE.match(line.lstrip())
    return bool(mok and m and m.group(1) == mok)


def _mark_hang_current(content: str, intent: OutlineIntent) -> str:
    rep = intent.primary_replacement
    if not rep:
        return content
    if intent.amendment_level == "hang":
        marked = content.replace(rep.old_text, f"<del>{rep.old_text}</del>")
        return marked if marked != content else content
    lines: list[str] = []
    for line in content.splitlines():
        if intent.amendment_level == "ho" and _line_matches_ho(line, intent.target_ho):
            lines.append(line.replace(rep.old_text, f"<del>{rep.old_text}</del>"))
        elif intent.amendment_level == "mok" and _line_matches_mok(line, intent.target_mok):
            lines.append(line.replace(rep.old_text, f"<del>{rep.old_text}</del>"))
        else:
            lines.append(line)
    return "\n".join(lines)


def _build_ho_mok_amended_block(content: str, intent: OutlineIntent, gpt_block: str) -> str:
    """호·목만 개정: 상위 항 전체를 펼치고 미변경 구간은 대시."""
    rep = intent.primary_replacement
    gpt_by_ho: dict[str, str] = {}
    for gl in gpt_block.splitlines():
        m = _HO_LINE_RE.match(gl.lstrip())
        if m:
            gpt_by_ho[m.group(1)] = gl

    draft_lines: list[str] = []
    for line in content.splitlines():
        lstripped = line.lstrip()
        if intent.amendment_level == "ho" and _line_matches_ho(line, intent.target_ho):
            gpt_line = gpt_by_ho.get(intent.target_ho, "")
            if _HAS_U_RE.search(gpt_line):
                draft_lines.append(gpt_line)
            elif rep and rep.old_text in line:
                draft_lines.append(line.replace(rep.old_text, f"<u>{rep.new_text}</u>"))
            else:
                draft_lines.append(line)
        elif intent.amendment_level == "mok" and _line_matches_mok(line, intent.target_mok):
            if rep and rep.old_text in line:
                draft_lines.append(line.replace(rep.old_text, f"<u>{rep.new_text}</u>"))
            else:
                draft_lines.append(line)
        else:
            draft_lines.append(line)

    return _process_kajeong_an("\n".join(draft_lines))


def _current_has_target_mark(marked: str, intent: OutlineIntent) -> bool:
    rep = intent.primary_replacement
    if not rep:
        return False
    needle = f"<del>{rep.old_text}</del>"
    if intent.amendment_level == "hang":
        return needle in marked
    for line in marked.splitlines():
        if intent.amendment_level == "ho" and _line_matches_ho(line, intent.target_ho):
            return needle in line
        if intent.amendment_level == "mok" and _line_matches_mok(line, intent.target_mok):
            return needle in line
    return False


def build_current_display(article: dict, intent: OutlineIntent, fallback: str = "") -> str:
    rep = intent.primary_replacement
    target_sym = hang_to_sym(intent.primary_hang) if intent.primary_hang else ""
    if not rep or not target_sym:
        return fallback

    blocks = split_hang_blocks(str(article.get("내용", "")))
    if not blocks:
        return fallback

    lines: list[str] = []
    for sym, content in blocks:
        if not sym:
            lines.append(content)
        elif sym == target_sym:
            marked = _mark_hang_current(content, intent)
            if not _current_has_target_mark(marked, intent):
                return fallback
            lines.append(marked)
        else:
            lines.append(f"{sym} (생략)")

    lines = compress_unchanged_hang_lines(lines, amended=False)
    return "\n".join(part for part in lines if part.strip())


def build_amended_display(
    article: dict,
    intent: OutlineIntent,
    gpt_amended: str,
) -> str:
    article_text = str(article.get("내용", ""))
    gpt_blocks = split_hang_blocks(gpt_amended)
    gpt_by_sym = {sym: content for sym, content in gpt_blocks if sym}
    changed_syms = {
        sym for sym, content in gpt_by_sym.items()
        if _HAS_U_RE.search(content) and "(현행과같음)" not in content
    }

    target_sym = hang_to_sym(intent.primary_hang) if intent.primary_hang else ""
    rep = intent.primary_replacement
    if intent.amendment_level in ("ho", "mok") and target_sym:
        changed_syms.add(target_sym)
    elif target_sym and rep:
        changed_syms.add(target_sym)

    result: list[str] = []
    for sym, content in gpt_blocks:
        if not sym:
            result.append(content)

    article_hangs = [(sym, content) for sym, content in split_hang_blocks(article_text) if sym]
    if not article_hangs:
        return gpt_amended

    for sym, orig in article_hangs:
        if sym in changed_syms:
            if intent.amendment_level in ("ho", "mok") and sym == target_sym:
                result.append(_build_ho_mok_amended_block(orig, intent, gpt_by_sym.get(sym, "")))
            elif sym in gpt_by_sym and _HAS_U_RE.search(gpt_by_sym[sym]):
                result.append(gpt_by_sym[sym])
            elif rep and sym == target_sym:
                marked = orig.replace(rep.old_text, f"<u>{rep.new_text}</u>")
                result.append(marked if marked != orig else gpt_by_sym.get(sym, f"{sym} (현행과같음)"))
            else:
                result.append(gpt_by_sym.get(sym, orig))
        else:
            result.append(f"{sym} (현행과같음)")

    result = compress_unchanged_hang_lines(result, amended=True)
    return "\n".join(part for part in result if part.strip()) or gpt_amended

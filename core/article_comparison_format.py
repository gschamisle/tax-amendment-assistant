"""현행·개정안 조문 표시 (항 압축, 호·목 개정 시 상위 전문·대시)."""
from __future__ import annotations

import re

from core.hwpx_writer import _dash_unchanged_segments
from core.outline_intent import OutlineIntent, hang_to_sym

_HANG_SYM_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")
_HO_LINE_RE = re.compile(r"^(\d+(?:의\d+)?)\.\s")
_MOK_LINE_RE = re.compile(r"^([가-힣])\.\s")
_HAS_U_RE = re.compile(r"<u>")
_INLINE_HANG_RE = re.compile(
    r"(제\d+조(?:의\d+)?[^①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]*)"
    r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])"
)


def normalize_inline_hang(text: str) -> str:
    """조 제목 뒤 인라인 ①을 줄바꿈으로 분리."""
    lines_pre: list[str] = []
    for line in text.splitlines():
        if not _HANG_SYM_RE.match(line.lstrip()):
            m = _INLINE_HANG_RE.search(line)
            if m:
                lines_pre.append(line[: m.start(2)].rstrip())
                lines_pre.append(line[m.start(2) :])
                continue
        lines_pre.append(line)
    return "\n".join(lines_pre)


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
    text = normalize_inline_hang(text)
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


def _extract_jo_title(article_text: str) -> str:
    first_line = article_text.splitlines()[0] if article_text.splitlines() else ""
    m = _INLINE_HANG_RE.search(first_line)
    if m:
        return first_line[: m.start(2)].rstrip()
    if _HANG_SYM_RE.match(first_line.lstrip()):
        return ""
    return first_line.rstrip()


def _line_matches_ho(line: str, ho: str) -> bool:
    m = _HO_LINE_RE.match(line.lstrip())
    return bool(ho and m and m.group(1) == ho)


def _line_matches_mok(line: str, mok: str) -> bool:
    m = _MOK_LINE_RE.match(line.lstrip())
    return bool(mok and m and m.group(1) == mok)


def _group_ho_lines(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """(호번호|None=항 도입부, 줄 목록)"""
    groups: list[tuple[str | None, list[str]]] = []
    current_ho: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, current_ho
        if buf:
            groups.append((current_ho, buf))
            buf = []

    for line in lines:
        m = _HO_LINE_RE.match(line.lstrip())
        if m:
            flush()
            current_ho = m.group(1)
            buf = [line]
        else:
            buf.append(line)
    flush()
    return groups


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


def _format_unchanged_ho_line(line: str) -> str:
    m = _HO_LINE_RE.match(line.lstrip())
    if not m:
        return line
    indent = line[: len(line) - len(line.lstrip())]
    return f"{indent}{m.group(1)}. (현행과같음)"


def _format_unchanged_mok_line(line: str) -> str:
    m = _MOK_LINE_RE.match(line.lstrip())
    if not m:
        return line
    indent = line[: len(line) - len(line.lstrip())]
    return f"{indent}{m.group(1)}. (현행과같음)"


def _apply_change_to_line(line: str, intent: OutlineIntent, gpt_line: str) -> str:
    if _HAS_U_RE.search(gpt_line):
        return _dash_unchanged_segments(gpt_line)
    rep = intent.primary_replacement
    if rep and rep.old_text in line:
        return _dash_unchanged_segments(line.replace(rep.old_text, f"<u>{rep.new_text}</u>"))
    return _dash_unchanged_segments(line) if _HAS_U_RE.search(line) else line


def _build_ho_mok_amended_block(content: str, intent: OutlineIntent, gpt_block: str) -> str:
    """호·목만 개정: 항 본문 유지, 미변경 호는 (현행과같음), 변경 호만 대시."""
    gpt_by_ho: dict[str, str] = {}
    gpt_by_mok: dict[str, str] = {}
    for gl in gpt_block.splitlines():
        hm = _HO_LINE_RE.match(gl.lstrip())
        if hm:
            gpt_by_ho[hm.group(1)] = gl
        mm = _MOK_LINE_RE.match(gl.lstrip())
        if mm:
            gpt_by_mok[mm.group(1)] = gl

    groups = _group_ho_lines(content.splitlines())
    result: list[str] = []

    for ho_key, lines in groups:
        if ho_key is None:
            result.extend(lines)
            continue

        if intent.amendment_level == "ho":
            if ho_key == intent.target_ho:
                for line in lines:
                    result.append(_apply_change_to_line(line, intent, gpt_by_ho.get(ho_key, "")))
            else:
                result.append(_format_unchanged_ho_line(lines[0]))
            continue

        if intent.amendment_level == "mok":
            for line in lines:
                if _line_matches_mok(line, intent.target_mok):
                    result.append(
                        _apply_change_to_line(line, intent, gpt_by_mok.get(intent.target_mok, ""))
                    )
                elif _MOK_LINE_RE.match(line.lstrip()):
                    result.append(_format_unchanged_mok_line(line))
                else:
                    result.append(line)
            continue

        result.extend(lines)

    return "\n".join(result)


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
    title = _extract_jo_title(normalize_inline_hang(str(article.get("내용", ""))))
    if title:
        lines.append(title)

    for sym, content in blocks:
        if not sym:
            if not title:
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
    article_text = normalize_inline_hang(str(article.get("내용", "")))
    gpt_blocks = split_hang_blocks(gpt_amended)
    gpt_by_sym = {sym: content for sym, content in gpt_blocks if sym}

    target_sym = hang_to_sym(intent.primary_hang) if intent.primary_hang else ""
    rep = intent.primary_replacement

    result: list[str] = []
    title = _extract_jo_title(article_text)
    if title:
        result.append(title)

    article_hangs = [(sym, content) for sym, content in split_hang_blocks(article_text) if sym]
    if not article_hangs:
        return gpt_amended

    for sym, orig in article_hangs:
        if sym == target_sym and intent.amendment_level in ("ho", "mok"):
            result.append(_build_ho_mok_amended_block(orig, intent, gpt_by_sym.get(sym, "")))
        elif sym == target_sym and rep and rep.old_text in orig:
            marked = orig.replace(rep.old_text, f"<u>{rep.new_text}</u>")
            result.append(marked)
        elif sym in gpt_by_sym and _HAS_U_RE.search(gpt_by_sym[sym]) and "(현행과같음)" not in gpt_by_sym[sym]:
            result.append(gpt_by_sym[sym])
        elif sym == target_sym:
            result.append(gpt_by_sym.get(sym, orig))
        else:
            result.append(f"{sym} (현행과같음)")

    result = compress_unchanged_hang_lines(result, amended=True)
    return "\n".join(part for part in result if part.strip()) or gpt_amended

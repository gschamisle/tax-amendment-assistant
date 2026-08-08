# -*- coding: utf-8 -*-
"""의견 분석 리포트(Markdown) → 공문서 HWPX.

  uv run python -m scripts.opinions_md_to_hwpx --bill 87936

군집 상세는 항목 나열 대신 **군집 1개 = 표 1개**로 바꾼다. 표의 행은
개요(의견 수~응집도) / 주요내용 / 요구사항 / 대표의견 발췌 4줄이고,
목차 순서(군집 순위)는 그대로 둔다.

셀 안 줄바꿈은 `<br>`로 쓴다 — kordoc이 HWPX의 별도 문단(`<hp:p>`)으로 만든다.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

_SECTION_RE = re.compile(r"^### (\d+)\. (.+?)$", re.M)
# 군집 상세는 다음 제목에서 끝난다. ###만 보면 마지막 군집이 뒤따르는
# '## 군집 전체 목록' 절을 통째로 셀 안에 삼킨다.
_NEXT_HEADING_RE = re.compile(r"^#{1,3} ", re.M)
_BULLET_RE = re.compile(r"^- \*\*(.+?)\*\*: (.*)$")
_LABEL_RE = re.compile(r"^\*\*(주요내용|요구사항|대표 의견 발췌)\*\*\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _cell(text: str) -> str:
    """표 셀 안전 문자열 — 파이프 이스케이프 + 굵게 표시 제거."""
    out = _BOLD_RE.sub(r"\1", text).replace("|", "／").strip()
    return re.sub(r"[ \t]+", " ", out)


def _join(lines: list[str]) -> str:
    return "<br>".join(_cell(ln) for ln in lines if _cell(ln))


def _parse_block(block: str) -> dict[str, list[str]]:
    """군집 본문을 개요/주요내용/요구사항/발췌로 가른다."""
    parts: dict[str, list[str]] = {"개요": [], "주요내용": [], "요구사항": [], "대표의견 발췌": []}
    current = "개요"
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        label = _LABEL_RE.match(line.strip())
        if label:
            current = "대표의견 발췌" if label.group(1) == "대표 의견 발췌" else label.group(1)
            continue
        bullet = _BULLET_RE.match(line)
        if bullet and current == "개요":
            # '스탠스: 반대 / 요구: 불명'처럼 한 줄에 둘이 든 항목도 그대로 둔다
            parts["개요"].append(f"{bullet.group(1)}: {bullet.group(2)}")
        elif line.startswith("- ") and current == "요구사항":
            parts["요구사항"].append("· " + line[2:])
        elif line.startswith(">"):
            parts["대표의견 발췌"].append(line.lstrip("> ").strip())
        else:
            parts[current].append(line)
    return parts


def transform(md: str) -> str:
    """군집 상세 섹션만 표로 바꾼다. 앞쪽 요약·분포는 원문 유지."""
    matches = list(_SECTION_RE.finditer(md))
    if not matches:
        return md

    out = [md[: matches[0].start()]]
    for i, m in enumerate(matches):
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        nxt = _NEXT_HEADING_RE.search(md, m.end(), section_end)
        body_end = nxt.start() if nxt else section_end
        body = md[m.end() : body_end]
        remainder = md[body_end:section_end]   # 뒤따르는 다른 절은 원문 그대로 둔다
        # 군집 상세 뒤 구분선도 표 밖으로 뺀다
        cut = body.find("\n---\n")
        if cut >= 0:
            body, remainder = body[:cut], body[cut:] + remainder

        parts = _parse_block(body)
        out.append(f"### {m.group(1)}. {m.group(2)}\n\n")
        out.append("| 구분 | 내용 |\n|------|------|\n")
        for key in ("개요", "주요내용", "요구사항", "대표의견 발췌"):
            out.append(f"| {key} | {_join(parts[key]) or '—'} |\n")
        out.append("\n" + remainder)
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bill", required=True, help="입법예고 ID (예: 87936)")
    ap.add_argument("--preset", default="보고서", help="kordoc 문서 프리셋")
    ap.add_argument("--src", default="", help="입력 md (기본: output/opinions-{bill}.md)")
    ap.add_argument("--out", default="", help="출력 hwpx (기본: output/opinions-{bill}.hwpx)")
    args = ap.parse_args()

    src = Path(args.src) if args.src else ROOT / "output" / f"opinions-{args.bill}.md"
    if not src.is_file():
        print(f"입력 없음: {src}", file=sys.stderr)
        print("→ 먼저 scripts/analyze_opinions.py 를 실행하세요.", file=sys.stderr)
        return 1

    staged = src.with_name(f"{src.stem}-hwpx소스.md")
    staged.write_text(transform(src.read_text(encoding="utf-8")), encoding="utf-8")
    out = Path(args.out) if args.out else src.with_suffix(".hwpx")

    # 산출물이 한글·뷰어에 열려 있으면 덮어쓰기가 막힌다. kordoc은 이때 "문서 처리 중
    # 오류"만 내놓아 원인을 알 수 없으므로, 임시 파일로 만든 뒤 교체하고 실패 사유를
    # 직접 말한다.
    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")
    cmd = ["npx", "-y", "kordoc@^4", "generate", str(staged), "-o", str(tmp),
           "--preset", args.preset]
    if subprocess.run(cmd, cwd=ROOT, shell=(sys.platform == "win32")).returncode != 0:
        print("HWPX 생성 실패", file=sys.stderr)
        return 1

    check = ["npx", "-y", "kordoc@^4", "validate", str(tmp)]
    if subprocess.run(check, cwd=ROOT, shell=(sys.platform == "win32")).returncode != 0:
        print("구조 검증 실패 — 한컴에서 열리지 않을 수 있습니다", file=sys.stderr)
        return 1

    try:
        tmp.replace(out)
    except OSError as exc:
        print(f"기존 파일을 덮어쓰지 못했습니다: {out}", file=sys.stderr)
        print(f"  → 한글이나 뷰어에서 열려 있으면 닫고 다시 실행하세요 ({exc})", file=sys.stderr)
        print(f"  → 생성된 파일은 여기 있습니다: {tmp}", file=sys.stderr)
        return 1

    print(f"\n생성: {out}")
    print(f"변환 소스: {staged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

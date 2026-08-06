"""PDF에서 뽑은 개정법률안 텍스트의 강제 개행을 논리 단위로 되붙인다.

HWPX는 '한 지시문 = 한 문단'이라 줄 단위 파싱(draft_bill_parser)이 그대로 통하지만,
PDF는 조판 폭에 맞춰 문장 중간에서 줄이 끊기고 사이에 빈 줄까지 섞여 들어온다.
그대로 넘기면 지시문의 서술어("…로 한다")가 다음 줄로 밀려 지시문 인식이 통째로 실패한다.

새 논리 단위를 여는 머리 토큰(조·항·호·목 기호, 개정문 시작, 대비표 경계)이 아니면
직전 줄에 이어 붙여 원래의 '한 지시문 = 한 줄' 형태로 복원한다.
"""
from __future__ import annotations

import re

# 새 논리 단위(줄)를 여는 머리 토큰
_HEAD_RE = re.compile(
    r"^(?:"
    r"제\d+조(?:의\d+)?"          # 지시문 / 신설 조문 본문
    r"|[①-⑳]"                    # 항
    r"|\d+(?:의\d+)?\."           # 호: "1." "1의2."
    r"|[가-힣]\."                 # 목: "가."
    r"|\d+\)"                     # 목 하위: "1)"
    r"|-\s"                       # 마크다운 리스트
    r"|#"                         # 헤딩
    r"|\|"                        # 표
    r"|부\s*칙"
    r"|제\d+장|제\d+절"
    r")"
)
# 줄 어디에 있어도 새 단위를 여는 신호 (개정문 시작·대비표 경계)
_BOUNDARY_RE = re.compile(r"일부를 다음과 같이 개정한다|신[ㆍ·]?구조문대비표")


def unwrap(text: str) -> str:
    """PDF 강제 개행을 되붙인 텍스트. HWPX 등 이미 문단 단위면 사실상 무해하다."""
    out: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if not out or _HEAD_RE.match(s) or _BOUNDARY_RE.search(s):
            out.append(s)
            continue
        prev = out[-1]
        # PDF 개행은 어절 중간에서도 일어난다 → 한글끼리는 공백 없이 붙인다
        joiner = "" if (prev and prev[-1] >= "가" and s[0] >= "가") else " "
        out[-1] = prev + joiner + s
    return "\n".join(out)

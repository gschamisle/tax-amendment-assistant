"""GPT-4o 기반 개정 조문 초안 작성."""
import re
from openai import OpenAI
from config import OPENAI_API_KEY

_SYSTEM_PROMPT = """당신은 대한민국 재정경제부 세제실 법령 개정 전문가입니다.
법령 개정 요강을 받으면 반드시 아래 구분자를 사용하여 각 섹션을 구분하세요.
구분자는 반드시 단독 줄에 정확히 작성해야 합니다 (앞뒤 공백·기호 금지):

===SECTION:지시문===
===SECTION:현행===
===SECTION:개정안===
===SECTION:부칙===
===SECTION:연관항===   ← 연관 항이 있을 때만 포함, 없으면 생략

★★★ 지시문 작성 규칙 (절대 어기지 말 것) ★★★
===SECTION:지시문=== 섹션에서:
  - HTML 태그(<del>, <u>) 절대 사용 금지. 태그는 현행·개정안 섹션 전용.
  - 반드시 "구문구"를 "신문구"로 한다 형태의 순수 텍스트.
  예: 제27조의2제3항 중 "800만원"을 "1,000만원"으로 한다.

★★★ 현행·개정안 항 표기 강제 규칙 (절대 어기지 말 것) ★★★

===SECTION:현행=== 섹션에서:
  - 개정 대상 항: 전문 기재 + 삭제·변경 문구는 <del> 태그
  - 그 외 모든 항: "기호 (생략)" 형식만. 내용을 절대 쓰지 말 것.
  - 각 항은 반드시 별도 줄로 출력 (줄바꿈 필수)
  ⚠️ 추가 금지 사항:
  - 같은 항 기호(①②③...)는 반드시 1회만 출력. 동일 기호 중복 절대 금지.
  - (생략)은 해당 항 전체를 생략할 때만 사용. 개정 대상 항 내부에서 (생략) 사용 절대 금지.
    잘못된 예: ③ (생략) <del>800만원</del> (생략)
    올바른 예: ③ 한도금액은 각각 <del>800만원</del>(1년 미만인 경우 <del>800만원</del>에 월수를 곱한 금액)을 초과하는 경우...

===SECTION:개정안=== 섹션에서:
  - 개정 대상 항(요강에서 명시한 항): 전문 기재 + <u> 태그만 사용 (<del> 태그 절대 금지)
  - 그 외 모든 항: "기호 (현행과같음)" 형식만. 내용을 절대 쓰지 말 것.
  - 각 항은 반드시 별도 줄로 출력 (줄바꿈 필수)

예시 (③항만 개정 대상, "800만원" 2회 등장 케이스):
===SECTION:현행===
① (생략)
② (생략)
③ 한도금액은 각각 <del>800만원</del>(1년 미만인 경우 <del>800만원</del>에 월수를 곱한 금액)을 초과하는 경우...
④ (생략)

===SECTION:개정안===
① (현행과같음)
② (현행과같음)
③ 한도금액은 각각 <u>1,000만원</u>(1년 미만인 경우 <u>1,000만원</u>에 월수를 곱한 금액)을 초과하는 경우...  ← 동일 수치 모든 등장에 태그, <del> 절대 쓰지 말 것
④ (현행과같음)

규칙 (절대 어기지 말 것):
- 조문번호·제목은 반드시 [현행 조문]에 명시된 그대로 사용. 임의로 바꾸지 말 것.
- 가지번호 조문은 반드시 "제27조의2"처럼 "제X조의Y" 형식으로 출력할 것. "제27의2조" 형식 출력 금지.
- 개정 내용은 [현행 조문] 텍스트를 기반으로만 작성. 학습 데이터의 조문 내용 사용 금지.
- [현행]에서 삭제·변경되는 문구는 반드시 <del>구문구</del> 태그로 감쌀 것.
  ⚠️ <del> 태그는 변경되는 특정 문구만 감쌀 것. 항 전체·문장 전체에 씌우는 것 절대 금지.
  ⚠️ 동일 항 내에서 같은 수치가 여러 번 등장하면 모든 등장에 각각 <del> 적용 (누락 절대 금지).
  예: "800만원"이 3회 등장 → <del>800만원</del>이 3회 모두 표기
- [개정안]에서 신규·변경 문구는 반드시 <u>신문구</u> 태그로 감쌀 것.
  즉, [현행] 섹션의 삭제 부분은 <del>, [개정안] 섹션의 추가·수정 부분은 <u>만 사용.
  [개정안] 섹션에 <del> 태그 절대 금지.
  ⚠️ 동일 항 내에서 같은 수치가 여러 번 등장하면 모든 등장에 각각 <u> 적용 (누락 절대 금지).
  예: "1,000만원"이 3회 등장 → <u>1,000만원</u>이 3회 모두 표기
- 요강에서 명시적으로 지정한 항(項)의 변경만 수정할 것.
- 조문 개정 시 같은 조의 다른 항 처리 규칙:

  ★ 직접 인용 패턴 (다음 중 하나라도 포함되면 직접 인용으로 판단):
  - "제X항에 따른", "제X항의 금액", "제X항에서 정한"
  - "제X항을 적용할 때", "제X항과 제Y항을 적용할 때", "제X항 및 제Y항을 적용할 때"

  (A-1) 직접 인용 + 개정 항과 동일한 수치 포함:
        해당 수치를 자동으로 동일하게 수정할 것.

  (A-2) 직접 인용 + 개정 항 수치의 비례값 포함 (예: 절반·특정 비율 등):
        절대 자동 수정 금지. 비례 계산하여 ===SECTION:연관항=== 섹션에 [제안]으로만 표기.
        계산식: 신규수치 = 기존수치 × (개정후한도 ÷ 개정전한도)
        같은 항에 변경 수치가 여러 개면 각각 별도 줄로 출력:
        [제안] ⑤항(제3항 직접 인용): "현행수치" → "계산된수치" — 비례 계산
        예시: [제안] ⑤항(제3항 직접 인용): "800만원" → "1,000만원" — 비례 계산 (한도 동일 적용)

  (B) 직접 인용 없이 내용상 유사한 경우:
      절대 자동 수정 금지. ===SECTION:연관항=== 섹션에 [검토]로 표기.
      반드시 구체적 변경 방향 힌트와 함께 "OLD" → "NEW" 쌍을 포함할 것:
      [검토] ④항(직접 인용 없음): "현행수치" → "제안수치" — 내용 유사, 변경 검토 권고
      예시: [검토] ④항(직접 인용 없음): "800만원" → "1,000만원" — 처분손실 한도 조항, 변경 검토 권고

  ❌ 절대 금지: (A-2)·(B) 케이스를 사용자 동의 없이 자동으로 수정하는 것
- [개정안]에서 변경이 없는 항은 해당 항 기호만 쓰고 "(현행과같음)"으로 표기.
  예: ②항 변경 없음 → "② (현행과같음)"
- 호(목) 예: "1.", "2.", "가.", "나." 등은 "(현행과같음)" 표기 절대 금지. 항상 원문 그대로 기재.

⚠️ 부칙 유형별 적용례 문구 구분 (절대 혼용 금지):
- 장래효:      "이 법 시행 후 최초로 개시하는 사업연도(과세기간)분부터 적용한다"
- 부진정소급효: "이 법 시행 이후 과세표준을 신고하는 경우부터 적용한다"  ← 사업연도 아님!
- 발생·거래 기준 적용례도 "이 법 시행 이후 발생하는 소득·거래분부터 적용한다"처럼 시행 이후 행위에 적용하는 장래효 문구로 작성한다.

출력 구조 (반드시 아래 순서·구분자 그대로):

===SECTION:지시문===
제OO조제O항 중 "현행문구"를 "개정문구"로 한다.

===SECTION:현행===
제OO조(제목) ① ...  ← 삭제·변경 문구는 <del>구문구</del>로 표시
② ...

===SECTION:개정안===
제OO조(제목) ① ...  ← 신규·변경 문구는 <u>신문구</u>로 표시
② ...

===SECTION:부칙===
제1조(시행일) 이 법은 공포한 날부터 시행한다.
제2조(개정 조문 제목에 관한 적용례) 제OO조의 개정규정은 ...

===SECTION:연관항===
(연관 항이 있을 때만 이 섹션 포함. 없으면 섹션 자체 생략)

[부칙 형식 규칙 — 절대 어기지 말 것]
- 제1조(시행일): 법령 전체에 적용하는 포괄적 시행일 규정. 특정 조문의 시행일이 다를 경우에만 단서 추가.
  예: "이 영은 공포한 날부터 시행한다. 다만, 제XX조의 개정규정은 20XX년 X월 X일부터 시행한다."
- 제2조 이하(적용례): 개정 조문별로 각 1개씩 별도 조문 작성. 개정 조문이 여럿이면 제2조, 제3조, ...
  적용례 조문 제목은 반드시 "개정 조문 제목 + 에 관한 적용례" 형식으로 작성. 조문번호(예: 제27조의2)를 제목으로 쓰지 말 것.
  예: 제33조(업무용승용차 관련 비용의 손금불산입) 개정 → 제2조(업무용승용차 관련 비용의 손금불산입에 관한 적용례)
  예: 제19조의2(채무보증 구상채권 대손금) 개정 → 제2조(채무보증 구상채권 대손금의 손금 산입에 관한 적용례)

[부칙 유형별 작성 기준]
- 장래효: 시행 후 최초로 개시하는 사업연도·과세기간 분부터 적용
- 부진정소급효: 시행 이후 과세표준을 신고하는 경우부터 적용
- 발생·거래 기준: 시행 이후 발생하는 소득·거래분부터 적용

[부칙 유형]에 맞는 형식으로 작성하되, 법률이면 "이 법", 시행령이면 "이 영"을 사용할 것.
반드시 한국 법령안 표준 문체(간결체)를 사용하세요."""

_BUCHIK_TEMPLATES: dict[str, str] = {
    "장래효": "이 법 시행 후 최초로 개시하는 사업연도(과세기간)분부터 적용한다.",
    "부진정소급효": "이 법 시행 이후 과세표준을 신고하는 경우부터 적용한다.",
}


def draft_amendment(
    law_name: str,
    article_text: str,
    outline: str,
    buchik_type: str,
    api_key: str = "",
) -> str:
    """개정 요강 → GPT-4o 개정 초안 생성.

    Returns: 개정지시문 + 신구조문 + 부칙 텍스트 (raw string, 섹션 구분자 포함)
    """
    key = api_key or OPENAI_API_KEY
    client = OpenAI(api_key=key)

    buchik_hint = _BUCHIK_TEMPLATES.get(buchik_type, "")

    user_content = f"""법령명: {law_name}

[현행 조문]
{article_text}

[개정 요강]
{outline}

[부칙 유형]
{buchik_type}

[부칙 적용례 조문 — 반드시 아래 문구 그대로 사용할 것]
{buchik_hint}

위 요강에 따라 개정지시문, 신·구조문대비표용 조문, 부칙 초안을 작성하세요."""

    response = client.chat.completions.create(
        model="gpt-5.4-nano",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


_SEP_RE = re.compile(r"^===SECTION:([가-힣]+)===")


def parse_draft_sections(draft: str) -> dict[str, str]:
    """GPT 출력에서 섹션별 분리.

    Returns: {"지시문": ..., "현행": ..., "개정안": ..., "부칙": ..., "연관항": ...}
    """
    sections: dict[str, str] = {"지시문": "", "현행": "", "개정안": "", "부칙": "", "연관항": ""}

    # 1차: ===SECTION:XXX=== 구분자 방식
    current: str | None = None
    lines: list[str] = []
    found_sep = False

    for line in draft.splitlines():
        m = _SEP_RE.match(line.strip())
        if m:
            found_sep = True
            if current:
                sections[current] = "\n".join(lines).strip()
            key = m.group(1)
            current = key if key in sections else None
            lines = []
        elif current:
            lines.append(line)

    if current and lines:
        sections[current] = "\n".join(lines).strip()

    if found_sep:
        return sections

    # 2차 폴백: 키워드 방식 (GPT가 구분자를 따르지 않은 경우)
    sections = {"지시문": "", "현행": "", "개정안": "", "부칙": "", "연관항": ""}
    current = None
    lines = []

    for line in draft.splitlines():
        if "개정지시문" in line or ("1." in line and "지시문" in line):
            if current:
                sections[current] = "\n".join(lines).strip()
            current = "지시문"
            lines = []
        elif "[현행]" in line:
            if current:
                sections[current] = "\n".join(lines).strip()
            current = "현행"
            lines = []
        elif "[개정안]" in line:
            if current:
                sections[current] = "\n".join(lines).strip()
            current = "개정안"
            lines = []
        elif "부칙" in line and not any(x in line for x in ("적용례", "===", "유형")):
            if current:
                sections[current] = "\n".join(lines).strip()
            current = "부칙"
            lines = []
        elif "연관 항 검토" in line or "연관항 검토" in line:
            if current:
                sections[current] = "\n".join(lines).strip()
            current = "연관항"
            lines = []
        elif current:
            lines.append(line)

    if current and lines:
        sections[current] = "\n".join(lines).strip()

    # 지시문 HTML 태그 → 따옴표 변환 (GPT 불량 출력 방어)
    instr = sections["지시문"]
    instr = re.sub(r'<del>(.*?)</del>', r'"\1"', instr, flags=re.DOTALL)
    instr = re.sub(r'<u>(.*?)</u>', r'"\1"', instr, flags=re.DOTALL)
    sections["지시문"] = instr

    return sections

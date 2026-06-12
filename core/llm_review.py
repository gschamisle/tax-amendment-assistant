"""업로드 개정안에 대한 Claude 판단 — 구조 해석 + 미반영 항목 삼분류.

결정적 레이어(draft_bill_parser + new_article_scanner)가 바닥이고,
LLM은 그 위에 판단만 얹는다:
  1. analyze_bill_structure — 개정문에서 신설 제도·조번호 범위를 추론해 입력을 보정
  2. review_missing_items — 미반영 후보를 누락(확신높음)/판단필요/조치불요로 삼분류,
     항목별 쟁점·권고조치·확신도 + 종합 검토의견

출력은 structured outputs(output_config.format)로 JSON 스키마를 강제한다 —
자유 텍스트 파싱 없이 UI가 안정적으로 렌더링하기 위함.
"""
from __future__ import annotations

import json

from config import ANTHROPIC_API_KEY

STRUCTURE_MODEL = "claude-fable-5"     # 구조 해석: 검토 빈도 낮고 정확도 결정적
ADJUDICATE_MODEL = "claude-sonnet-4-6"  # 항목 판별: 항목 수 많고 패턴 정형적

_STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "제도명": {"type": "string", "description": "신설되는 제도의 명칭"},
        "제도_요약": {"type": "string", "description": "신설 제도의 내용 2~3문장 요약"},
        "신설_조번호": {
            "type": "array", "items": {"type": "string"},
            "description": "새 제도가 차지하는 조번호 (예: '29', '29의2'). 제목 변경으로 기존 조문을 대체하는 경우 포함, 존치·개정되는 조문은 제외",
        },
        "존치_개정_조번호": {
            "type": "array", "items": {"type": "string"},
            "description": "내용이 유지되면서 일부 개정·절 재편성만 되는 조번호",
        },
        "비고": {"type": "string", "description": "범위 판단 시 주의할 점 (절 재편성, 번호 재사용 등)"},
    },
    "required": ["제도명", "제도_요약", "신설_조번호", "존치_개정_조번호", "비고"],
    "additionalProperties": False,
}

_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "종합의견": {
            "type": "string",
            "description": "개정안 전체에 대한 검토의견 3~5문장. 가장 중요한 쟁점을 먼저, 정형 연동의 충실도 평가, 부칙·경과조치 필요성 순으로",
        },
        "항목": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "법령명": {"type": "string"},
                    "조번호": {"type": "string", "description": "예: '127', '30의4'"},
                    "구분": {
                        "type": "string",
                        "enum": ["누락", "판단필요", "조치불요"],
                        "description": "누락=개정 필요한데 빠짐(확신 높음), 판단필요=정책 판단 사항, 조치불요=비해당 또는 현행 유지가 타당",
                    },
                    "쟁점": {"type": "string", "description": "왜 문제인지 또는 왜 비해당인지 1~2문장"},
                    "권고조치": {
                        "type": "string",
                        "description": "개정문에 추가 / 부칙 경과조치 / 비해당 확인 등 구체적 조치",
                    },
                    "확신도": {"type": "string", "enum": ["높음", "중간", "낮음"]},
                },
                "required": ["법령명", "조번호", "구분", "쟁점", "권고조치", "확신도"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["종합의견", "항목"],
    "additionalProperties": False,
}

_STRUCTURE_SYSTEM = (
    "당신은 기획재정부 세제실의 법령 입안 검토관이다. 일부개정법률안의 개정문을 읽고 "
    "신설 제도가 차지하는 조번호 범위를 정확히 판별한다.\n"
    "주의: '제X조의 제목 …를 …로 하고'는 기존 조문을 새 내용으로 대체(사실상 신설)하는 형식이다. "
    "반면 절(節) 번호·제목만 신설되거나 기존 제도가 문구 수정으로 존치되는 조문은 신설이 아니다. "
    "지시문을 하나씩 따라가며 판단하라."
)

_REVIEW_SYSTEM = (
    "당신은 기획재정부 세제실의 법령 입안 검토관이다. 신설 제도 개정안에서 병행개정이 "
    "누락됐을 가능성이 있는 조문 목록을 받아, 각 항목을 검토해 삼분류한다.\n\n"
    "분류 기준:\n"
    "- 누락: 신설 제도의 성격상 해당 조문 개정(열거 추가·인용 정비)이 필요한데 개정안에 없음. "
    "확신이 높을 때만 사용\n"
    "- 판단필요: 적용 여부가 정책 판단(예: 수도권 배제 적용 여부)이거나 정보가 부족함\n"
    "- 조치불요: 구 조문 인용이 이월공제·경과규정 목적으로 존치되는 것이 타당하거나, "
    "유사 제도 인용이 신설 제도와 무관함\n\n"
    "판단 시 고려: 세액공제 신설의 정형 연동(중복지원 배제 제127조, 최저한세 제132조, "
    "이월공제 제144조, 추계 시 배제, 구분경리, 농어촌특별세), 조번호 재사용 시 잔존 인용의 "
    "의미 왜곡, 부칙 경과조치로 풀어야 할 사항. 권고조치는 실무자가 바로 실행할 수 있게 구체적으로.\n\n"
    "중요: 미반영_후보 목록의 모든 조문은 검증 결과 개정안에 해당 조문을 고치는 지시문이 "
    "없는 것으로 확인된 조문이다. 따라서 '이미 개정안에 반영되어 있다'는 분류 근거는 성립할 수 "
    "없다 — 참고용 반영 목록은 다른 조문이며, 후보를 면제시키는 근거로 쓰지 마라. 조치불요는 "
    "오직 '신설 제도와 무관하거나 현행 유지가 법리상 타당'할 때만 사용한다."
)


def _client(api_key: str = ""):
    from anthropic import Anthropic

    key = api_key or ANTHROPIC_API_KEY
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다 (.env 확인)")
    return Anthropic(api_key=key)


def _structured_call(model: str, system: str, user_text: str, schema: dict, api_key: str = "") -> dict:
    with _client(api_key).messages.stream(
        model=model,
        max_tokens=64000,  # adaptive thinking 토큰 포함 — 빠듯하면 JSON이 잘린다 (Sonnet 스트리밍 상한)
        thinking={"type": "adaptive"},
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user_text}],
    ) as stream:
        response = stream.get_final_message()
    text = "".join(b.text for b in response.content if b.type == "text")
    if response.stop_reason != "end_turn" or not text.strip():
        raise RuntimeError(
            f"LLM 응답 비정상 (stop_reason={response.stop_reason}, text_len={len(text)})"
        )
    return json.loads(text)


def analyze_bill_structure(body: str, api_key: str = "") -> dict:
    """개정문 본문에서 신설 제도와 조번호 범위를 추론한다."""
    user = (
        "다음 일부개정법률안 개정문을 분석해 신설 제도가 차지하는 조번호 범위를 판별하라.\n\n"
        f"<개정문>\n{body[:60000]}\n</개정문>"
    )
    return _structured_call(STRUCTURE_MODEL, _STRUCTURE_SYSTEM, user, _STRUCTURE_SCHEMA, api_key)


def review_missing_items(
    missing_items: list[dict],
    bill_summary: str,
    new_block: str,
    manual_targets: list[str],
    api_key: str = "",
) -> dict:
    """미반영 후보를 삼분류하고 종합 검토의견을 생성한다.

    Args:
        missing_items: [{법령명, 조번호, 제목, 대상?, 인용?, 출처(잔존|프록시)}]
        bill_summary: 신설 제도 요약 (analyze_bill_structure의 제도_요약 등)
        new_block: 신설 조문 본문 발췌
        manual_targets: 수기 병행개정이 이미 반영된 조번호 목록
    """
    payload = {
        "신설_제도_요약": bill_summary,
        "참고_개정안에_이미_지시문이_있는_조문(아래 후보와 무관)": manual_targets,
        "미반영_후보(전부 개정안에 지시문 없음)": missing_items,
    }
    user = (
        "신설 조문 본문(발췌)과 미반영 후보 목록이다. 각 후보를 삼분류하고 종합의견을 작성하라.\n\n"
        f"<신설_조문_본문>\n{new_block[:30000]}\n</신설_조문_본문>\n\n"
        f"<검토_자료>\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n</검토_자료>"
    )
    return _structured_call(ADJUDICATE_MODEL, _REVIEW_SYSTEM, user, _REVIEW_SCHEMA, api_key)


def run_llm_review(cmp_result: dict, body: str, api_key: str = "") -> dict:
    """compare_review 결과에 LLM 판단을 얹는다.

    Returns:
        {"구조": {...}, "검토": {"종합의견": str, "항목": [...]}}
    """
    structure = analyze_bill_structure(body, api_key)

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in cmp_result["stale"]["missing"]:
        key = (row["법령명"], str(row["조번호"]))
        seen.add(key)
        items.append({
            "법령명": row["법령명"],
            "조번호": str(row["조번호"]),
            "제목": row.get("제목", ""),
            "재사용_번호_인용": row.get("대상", []),
            "인용_구문": row.get("인용", [])[:3],
            "출처": "잔존 인용 (재사용 조번호를 현행법이 인용 중)",
        })
    for row in cmp_result["proxy"]["missing"]:
        key = (row["법령명"], str(row["조번호"]))
        if key in seen:
            continue
        items.append({
            "법령명": row["법령명"],
            "조번호": str(row["조번호"]),
            "제목": row.get("제목", ""),
            "인용_구문": row.get("인용", [])[:3],
            "출처": "유사 제도 체크리스트 (프록시 조문을 인용하는 열거형 조문)",
        })

    from core.draft_bill_parser import new_range_block

    jo_list = cmp_result["jo_list"]
    block = new_range_block(body, jo_list) if body else ""

    review = review_missing_items(
        items,
        structure.get("제도_요약", ""),
        block,
        cmp_result["manual_targets"],
        api_key,
    )
    return {"구조": structure, "검토": review}

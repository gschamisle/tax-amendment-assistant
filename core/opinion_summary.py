"""상위 군집 요약 — Claude 보조 레이어.

군집화·태깅은 전부 결정적 레이어가 끝낸 상태다. 여기서 LLM이 하는 일은 하나뿐이다:
**이미 확정된 군집의 내용을 사람이 읽을 문장으로 옮기는 것.** 어떤 의견이 어느 군집에
속하는지, 건수가 몇인지는 LLM이 건드리지 않는다 — 그래서 요약이 틀려도 통계는 안 흔들린다.

호출량은 "상위 X개 군집" 수만큼이다(기본 20회). 군집 구성이 그대로면 캐시가 받아내
재실행은 무과금이고, `--no-llm`이면 이 모듈을 아예 타지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from core.llm_review import structured_call

SUMMARY_MODELS = ["claude-sonnet-4-6", "claude-haiku-4-5"]

_REP_LIMIT = 3000     # 대표의견 절단 길이(자)
_SAMPLE_LIMIT = 1200  # 표본 의견 절단 길이(자)
_MAX_SAMPLES = 5

_SYSTEM = (
    "당신은 대한민국 재정경제부 세제실에서 입법예고 의견을 정리하는 실무자입니다.\n"
    "같은 취지의 의견 여러 건을 묶은 '의견 군집' 하나가 주어집니다. 이 군집이 무엇을 "
    "말하는지 보고자료용으로 정리하세요.\n\n"
    "원칙:\n"
    "- 주어진 의견에 실제로 담긴 내용만 쓴다. 없는 주장·통계·법령을 지어내지 않는다.\n"
    "- 감정적 표현은 중립적 행정 문어로 옮기되, 요구의 강도는 왜곡하지 않는다.\n"
    "- 요구사항은 정부가 취할 수 있는 조치 단위로 끊어 쓴다(예: '기본공제 12억원으로 상향').\n"
    "- 의견이 특정 조문을 지목했으면 관련조문에 적고, 없으면 빈 배열로 둔다. 추측해서 "
    "조문번호를 만들지 않는다.\n"
    "- 대표인용은 군집의 취지를 가장 잘 보여주는 문장을 원문에서 그대로 발췌한다(1~2문장). "
    "개인정보·욕설은 발췌하지 않는다."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "쟁점명": {
            "type": "string",
            "description": "이 군집을 한 줄로 부르는 이름 (20자 내외, 예: '1세대 1주택 종부세 폐지 요구')",
        },
        "주요내용": {
            "type": "string",
            "description": "군집 의견의 요지 3~4문장. 무엇에 대해 어떤 이유로 무엇을 요구하는지 순서로",
        },
        "요구사항": {
            "type": "array",
            "items": {"type": "string"},
            "description": "정부에 요구하는 구체적 조치 목록 (1~5개, 각 30자 내외)",
        },
        "스탠스": {
            "type": "string",
            "enum": ["찬성", "반대", "조건부", "기타"],
            "description": "입법예고안에 대한 태도. 판단이 어려우면 '기타'",
        },
        "대표인용": {"type": "string", "description": "원문에서 그대로 발췌한 1~2문장"},
        "관련조문": {
            "type": "array",
            "items": {"type": "string"},
            "description": "의견이 지목한 조문 (예: '제7조'). 없으면 빈 배열",
        },
    },
    "required": ["쟁점명", "주요내용", "요구사항", "스탠스", "대표인용", "관련조문"],
    "additionalProperties": False,
}


@dataclass
class ClusterBrief:
    """LLM에 넘기는 군집 1개의 요약 입력."""
    cluster_id: int
    size: int
    share: float
    representative: str
    samples: list[str] = field(default_factory=list)
    top_terms: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)
    stance_hint: str = ""
    demand_hint: str = ""

    def cache_key(self) -> str:
        """군집 구성이 같으면 같은 키 — 재실행 시 API를 다시 때리지 않는다."""
        seed = json.dumps(
            {
                "size": self.size,
                "rep": self.representative[:_REP_LIMIT],
                "samples": sorted(s[:_SAMPLE_LIMIT] for s in self.samples[:_MAX_SAMPLES]),
                "articles": sorted(self.articles),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def to_prompt(self, law_name: str = "") -> str:
        samples = self.samples[:_MAX_SAMPLES]
        payload = {
            "대상법률": law_name,
            "군집_의견수": self.size,
            "전체_대비_비율": f"{self.share * 100:.1f}%",
            "핵심_키워드": self.top_terms,
            "규칙기반_관련조문": self.articles,
            "규칙기반_찬반_추정": self.stance_hint,
            "규칙기반_요구_추정": self.demand_hint,
        }
        blocks = [f"<군집정보>\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n</군집정보>"]
        blocks.append(f"<대표의견>\n{self.representative[:_REP_LIMIT]}\n</대표의견>")
        for i, sample in enumerate(samples, start=1):
            blocks.append(f"<표본의견{i}>\n{sample[:_SAMPLE_LIMIT]}\n</표본의견{i}>")
        blocks.append(
            "위 군집의 쟁점명·주요내용·요구사항·스탠스·대표인용·관련조문을 정리하라. "
            "규칙기반 추정치는 참고만 하고, 실제 의견 내용과 다르면 의견을 따르라."
        )
        return "\n\n".join(blocks)


def _load_cache(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(path: Path | None, cache: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_clusters(
    briefs: Sequence[ClusterBrief],
    *,
    law_name: str = "",
    api_key: str = "",
    cache_file: Path | str | None = None,
    models: Sequence[str] | None = None,
    progress: Callable[[int, int, bool], None] | None = None,
) -> dict[int, dict[str, Any]]:
    """군집별 요약을 만든다. 실패한 군집은 결과에서 빠지고 리포트는 결정적 라벨로 채운다.

    Returns: {cluster_id: {쟁점명, 주요내용, 요구사항, 스탠스, 대표인용, 관련조문}}
    """
    cache_path = Path(cache_file) if cache_file else None
    cache = _load_cache(cache_path)
    model_list = list(models or SUMMARY_MODELS)

    out: dict[int, dict[str, Any]] = {}
    dirty = False
    for i, brief in enumerate(briefs, start=1):
        key = brief.cache_key()
        cached = cache.get(key)
        if cached:
            out[brief.cluster_id] = cached
            if progress:
                progress(i, len(briefs), True)
            continue
        try:
            result = structured_call(
                model_list, _SYSTEM, brief.to_prompt(law_name), _SCHEMA, api_key
            )
        except Exception as exc:  # 한 군집이 실패해도 나머지 리포트는 완성한다
            if progress:
                progress(i, len(briefs), False)
            out[brief.cluster_id] = {"_error": str(exc)}
            continue
        cache[key] = result
        out[brief.cluster_id] = result
        dirty = True
        if progress:
            progress(i, len(briefs), False)

    if dirty:
        _save_cache(cache_path, cache)
    return out

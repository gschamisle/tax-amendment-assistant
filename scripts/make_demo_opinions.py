"""데모·보정용 합성 의견 코퍼스 생성 — **실제 수집 데이터가 아니다.**

실제 사이트에서 의견을 받기 전에 파이프라인을 시험하거나, 유사도 임계값·쟁점 사전을
바꾼 뒤 그 영향을 재보정할 때 쓴다. 실제 입법예고 의견의 분포 특성을 흉내낸다:

  * 복붙 캠페인이 큰 덩어리를 차지 (테마별 35~55%가 완전히 같은 문구)
  * 같은 주장의 표현만 다른 변형이 그 주변에 깔림
  * 인사말·맺음말이 40% 정도에 붙음
  * 조문 인용은 일부에만
  * 서로 관련 없는 롱테일 의견

**`테마` 열이 정답 라벨이다.** 파서는 이 열을 무시하므로(알려진 열 이름만 매핑) 그대로
`--from-files`에 넣어도 되고, 군집 결과와 대조해 순도·재현율을 실측할 수도 있다.

사용:
  uv run python scripts/make_demo_opinions.py
  uv run python scripts/make_demo_opinions.py --scale 3 --out output/big.csv   # 성능 시험
  uv run python scripts/analyze_opinions.py --bill DEMO --law 종합부동산세법 \
      --top 12 --no-llm --from-files output/demo-opinions.csv

⚠️ 생성물은 합성 데이터다. 리포트 숫자를 정책 근거로 인용해서는 안 된다.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_OUT = ROOT / "output" / "demo-opinions.csv"
DEFAULT_SEED = 20260807

# (테마, 목표 건수, 복붙 비율, [표현 변형들])
THEMES: list[tuple[str, int, float, list[str]]] = [
    ("1주택폐지", 400, 0.55, [
        "1세대 1주택자에 대한 종합부동산세는 폐지되어야 합니다. 실거주 목적으로 평생 살아온 집에 세금을 매기는 것은 재산권 침해이며 재산세와의 이중과세입니다.",
        "1세대 1주택 실거주자에게 종부세를 부과하는 것은 부당합니다. 집 한 채가 전부인 국민에게 미실현이득을 과세하는 것은 헌법상 재산권을 침해합니다.",
        "실거주 1주택자는 종합부동산세 과세 대상에서 제외해 주십시오. 팔 생각이 없는 집인데 오르지도 않은 이익에 세금을 내라는 것은 납득하기 어렵습니다.",
        "1가구 1주택에 대한 종부세는 폐지해 주시기 바랍니다. 제7조를 삭제하여 실거주 주택은 과세 대상에서 빼 주십시오.",
        "평생 한 집에서 살아온 사람에게 종부세를 물리는 것은 이중과세입니다. 재산세를 이미 내고 있는데 또 국세를 걷는 것은 부당하므로 1주택자는 제외해야 합니다.",
    ]),
    ("공정시장가액", 250, 0.45, [
        "공정시장가액비율을 60%로 인하하여 주십시오. 공시가격이 급등하여 소득은 그대로인데 세부담만 감당하기 어려운 수준으로 늘었습니다.",
        "공정시장가액비율을 낮춰 주십시오. 공시가격 현실화로 실제 소득과 무관하게 세금이 몇 배로 뛰었습니다.",
        "공시가격 현실화율을 재검토하고 공정시장가액비율을 60% 수준으로 환원해 주시기 바랍니다.",
        "공정시장가액비율 인하를 요청드립니다. 시세가 오르지 않았는데 공시가격만 올라 세부담이 급증하는 구조는 개선되어야 합니다.",
    ]),
    ("중과유지찬성", 210, 0.40, [
        "다주택자 중과세율은 유지되어야 합니다. 투기 억제를 위하여 종합부동산세 강화에 찬성합니다.",
        "이번 개정안에 찬성합니다. 다주택자에 대한 중과는 부동산 투기를 막는 최소한의 장치이므로 완화해서는 안 됩니다.",
        "종부세 완화에 반대합니다. 다주택 보유에 대한 과세를 오히려 강화하여 실수요자 중심으로 시장을 정상화해야 합니다.",
        "투기 수요 억제를 위해 다주택자 중과세율을 그대로 유지해 주십시오. 감세는 부동산 가격 상승만 부추깁니다.",
    ]),
    ("세부담상한", 170, 0.35, [
        "세부담 상한을 낮추어 주시기 바랍니다. 제10조의 상한 규정이 있어도 매년 세금이 급증해 실효성이 없습니다.",
        "세부담 상한제를 실질화해 주십시오. 상한이 있다지만 공시가격이 오르면 결국 매년 큰 폭으로 늘어납니다.",
        "급격한 세부담 증가를 막을 수 있도록 세부담 상한 비율을 인하해 주시기 바랍니다.",
    ]),
    ("고령자공제", 150, 0.35, [
        "고령자 세액공제와 장기보유 공제를 확대해 주십시오. 소득이 없는 은퇴자에게 제9조의 부담은 과도합니다.",
        "연금으로 생활하는 고령자에게 종부세는 너무 큰 부담입니다. 고령자 공제율을 높이고 장기보유 공제 한도를 확대해 주십시오.",
        "20년 넘게 한 집에 산 고령자에게는 종합부동산세를 감면해 주시기 바랍니다. 소득이 없는데 세금만 늘어납니다.",
        "고령자·장기보유 공제 합산 한도를 상향해 주십시오. 은퇴 후 소득이 없는 계층에 대한 배려가 필요합니다.",
    ]),
    ("법인강화", 95, 0.45, [
        "법인 소유 주택에 대한 종합부동산세는 더욱 강화되어야 합니다. 법인을 통한 우회 취득을 반드시 막아야 합니다.",
        "법인 명의로 주택을 사들이는 편법을 막기 위해 법인에 대한 종부세 중과를 유지해 주십시오. 찬성합니다.",
        "법인의 주택 보유에 대해서는 기본공제를 두지 말고 중과세율을 그대로 적용해야 합니다.",
    ]),
    ("임대주택", 85, 0.35, [
        "임대주택 합산배제 요건을 완화해 주십시오. 등록임대사업자의 부담이 지나치게 커졌습니다.",
        "등록임대주택에 대한 합산배제를 복원해 주시기 바랍니다. 제도를 믿고 등록한 사업자가 피해를 보고 있습니다.",
        "매입임대·건설임대 합산배제 요건이 너무 엄격합니다. 요건을 현실에 맞게 조정해 주십시오.",
    ]),
    ("지방세전환", 70, 0.50, [
        "종합부동산세를 폐지하고 재산세로 통합하여 지방세로 전환해 주십시오. 국세로 걷는 보유세는 이중과세 구조를 만듭니다.",
        "보유세는 지방세인 재산세로 일원화해야 합니다. 종부세를 국세로 유지할 이유가 없습니다.",
    ]),
    ("기본공제상향", 65, 0.40, [
        "기본공제 금액을 12억원으로 상향해 주십시오. 물가와 집값 상승을 반영하지 못한 과세기준금액은 조정되어야 합니다.",
        "과세기준금액을 현실에 맞게 올려 주시기 바랍니다. 9억원 기준은 지금 서울에서 아무 의미가 없습니다.",
    ]),
    ("부칙경과", 55, 0.40, [
        "부칙에 경과조치를 두어 시행일 전 취득분에는 종전 규정을 적용해 주시기 바랍니다. 소급 적용은 신뢰보호 원칙에 어긋납니다.",
        "시행일 이전에 계약한 경우에는 종전 규정을 적용하는 경과조치가 필요합니다.",
    ]),
]

# 빈 문자열이 섞여 있어 대략 절반에만 인사말·맺음말이 붙는다.
GREETINGS = ["안녕하십니까. ", "존경하는 담당자님께. ", "국민의 한 사람으로서 의견 드립니다. ", "", "", ""]
CLOSINGS = [
    " 적극 검토를 부탁드립니다. 감사합니다.",
    " 부디 반영해 주시기 바랍니다. 감사합니다.",
    " 감사합니다.",
    "", "", "",
]
EMPHASIS = ["", "", " 꼭 재고해 주십시오.", " 다시 한 번 요청드립니다.", " 국민의 목소리를 들어 주십시오."]

LONGTAIL = [
    "입법예고 기간이 너무 짧습니다. 의견을 낼 시간을 더 주십시오.",
    "홈페이지에서 의견 제출이 자꾸 실패합니다. 시스템을 개선해 주세요.",
    "종부세 세수는 어디에 쓰이는지 사용 내역을 공개해 주시기 바랍니다.",
    "농지와 임야에 대한 과세 기준도 함께 정비해 주십시오.",
    "상속으로 취득한 주택은 별도 기준을 적용해 주시기 바랍니다.",
    "이혼으로 일시적 2주택이 된 경우 예외를 인정해 주십시오.",
    "지방 저가주택은 주택 수에서 제외해 주시기 바랍니다.",
    "재개발 입주권도 주택 수에 넣는 것은 부당합니다.",
    "부부 공동명의 특례 신청 기한을 늘려 주십시오.",
    "종부세 고지서 산출 근거를 알기 쉽게 표시해 주세요.",
    "1주택자 특례 신청 절차가 너무 복잡합니다. 간소화해 주십시오.",
    "청년·신혼부부 첫 주택은 과세 대상에서 빼 주시기 바랍니다.",
    "외국인 다주택 보유에 대한 과세를 강화해 주십시오.",
    "빈집에 대해서는 더 높은 세율을 적용해야 합니다.",
    "전세를 낀 주택은 실질 소유로 보기 어려우니 조정이 필요합니다.",
    "세무서 상담 인력을 늘려 주시기 바랍니다.",
    "공시가격 이의신청 절차를 개선해 주십시오.",
    "과세표준 구간을 물가에 연동해 자동 조정되도록 해 주세요.",
    "종부세 분납 기준을 완화해 주시기 바랍니다.",
    "장애인 가구에 대한 감면 규정을 신설해 주십시오.",
]
LONGTAIL_COUNT = 120

# 가상의 이름 — 실존 인물과 무관하다. 작성자 마스킹 경로를 태우기 위한 값일 뿐이다.
NAMES = [f"{s}{m}{e}" for s in "김이박최정강조윤장임" for m in "민서지" for e in "우준현"]

_SPREAD_DAYS = 18  # 접수일을 이 기간에 걸쳐 분산


def build(scale: float, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[tuple[str, str]] = []  # (본문, 정답 테마)

    for theme, count, dup_ratio, variants in THEMES:
        base = variants[0]
        for _ in range(max(1, round(count * scale))):
            if rng.random() < dup_ratio:
                body = base  # 복붙 캠페인
            else:
                body = (
                    rng.choice(GREETINGS)
                    + rng.choice(variants)
                    + rng.choice(EMPHASIS)
                    + rng.choice(CLOSINGS)
                )
            rows.append((body, theme))

    for i in range(max(1, round(LONGTAIL_COUNT * scale))):
        text = LONGTAIL[i % len(LONGTAIL)]
        if i >= len(LONGTAIL):  # 두 바퀴째부터는 인사말을 붙여 변형을 만든다
            text = rng.choice(GREETINGS) + text + rng.choice(CLOSINGS)
        rows.append((text, "롱테일"))

    rng.shuffle(rows)
    out: list[dict[str, str]] = []
    for i, (body, theme) in enumerate(rows):
        day = 10 + i * _SPREAD_DAYS // len(rows)
        out.append({
            "번호": str(500000 + i),
            "작성자": rng.choice(NAMES),
            "등록일": f"2026.07.{day:02d}",
            "의견내용": body,
            "테마": theme,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="합성 입법예고 의견 코퍼스 생성 (실제 데이터 아님)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="출력 CSV 경로")
    parser.add_argument("--scale", type=float, default=1.0, help="건수 배율 (성능 시험용)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="난수 시드 (같으면 결과 동일)")
    args = parser.parse_args(argv)

    rows = build(args.scale, args.seed)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["번호", "작성자", "등록일", "의견내용", "테마"])
        writer.writeheader()
        writer.writerows(rows)

    truth = Counter(r["테마"] for r in rows)
    print(f"⚠️ 합성 데이터입니다 — 실제 수집 의견이 아닙니다.\n")
    print(f"{len(rows):,}건 생성 → {path}")
    print(f"정답 테마 {len(truth)}종:")
    for theme, count in truth.most_common():
        print(f"  {count:>5,}  {theme}")
    print(
        "\n다음: uv run python scripts/analyze_opinions.py --bill DEMO --law 종합부동산세법 "
        f"--top 12 --no-llm --from-files {path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

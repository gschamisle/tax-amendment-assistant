# 세법개정 AI 어시스턴트

> **세법을 개정할 때 함께 고쳐야 할 연관 조문을 빠뜨리지 않는 것** — 이것이 이 도구의 제1원칙입니다.

대한민국 재정경제부 세제실 업무를 위한 법령 개정 보조 도구. 법제처 Open API로 현행 법령을 조회해, 어떤 조문을 개정할 때 **함께 손봐야 하는 인용·준용·역인용·병행·별표 조문을 결정적으로(추측이 아니라 규칙·그래프로) 찾아냅니다.**

---

## 제1원칙 — 연관 조문 누락 방지

한 조문을 고치면, 그 조문을 **인용·준용·병행**하거나 그 조문과 엮인 **별표**도 함께 개정해야 하는 경우가 많습니다. 이 연결을 사람이 머리로 추적하면 빠뜨리기 쉽고, 빠뜨리면 법령 간 충돌·적용 오류로 이어집니다. **이 도구의 존재 이유는 그 누락을 막는 것입니다.**

그래서 연관 조문 탐지는 **LLM 추측에 의존하지 않습니다.** 인용 파서·인용 그래프·병행 매트릭스 같은 **결정적 레이어**로 후보를 빠짐없이 찾고, 정말 애매한 판단만 사람(또는 Claude 보조 검토)에게 맡깁니다. "애매하면 포함하고 사람이 검토" — 누락(false negative)을 가장 경계합니다.

### 5가지 연관 분류

| 분류 | 의미 | 채우는 방식 |
|------|------|------------|
| **인용** | 이 조문이 끌어쓰는 조문 | 인용 파서 |
| **준용** | "준용한다"로 끌어쓴 조문 | 인용 파서 |
| **역인용** | 이 조문을 인용하는 다른 조문 (개정 영향) | 인용 그래프 |
| **병행개정** | 짝 세법의 대응 조문 (소득세법↔법인세법 등) | 병행 매트릭스 |
| **별표** | 이 조문과 엮인 별표·별지서식 (양방향) | 별표 인덱스 |

---

## 보완 예정 — 제1원칙이 충분히 성숙한 뒤

다음 기능은 **누락 방지가 완벽에 가까워진 후에 보완**할 영역입니다. 지금은 보조·준비 단계입니다.

- **개정 초안 생성** (개정요강 → 신·구조문대비표 초안): 현재 OpenAI 기반 *보조* 기능.
- **HWPX 출력**: **현재 베타에서 비활성화되어 있습니다**(`config.ENABLE_HWPX_OUTPUT`). 탭은 "준비 중"으로 표시되며, 정식 제공은 추후 안내합니다.

> 우선순위가 분명합니다 — **먼저 "절대 안 빠뜨린다"를 완성하고, 그 위에 초안·출력 편의를 얹습니다.**

---

## 핵심 기능 (현재)

- **연관 조문 4+1분류** — 개정 조문을 직접 입력하면 인용/준용/역인용/병행/별표로 구분해 연관 조문만 구조화 (GPT 없이 결정적 분석).
- **신설 조문 검토** — ① 신설안이 인용하는 조문 ② 재사용 조번호 잔존 인용 충돌 ③ 유사 제도 체크리스트 ④ 관련 별표. 개정안 파일 업로드 시 수기 병행개정과 자동 대조.
- **폭넓은 인용 파싱** — `제X조`, 가지번호(`제3조의2`), 범위(`제2조부터 제8조까지`·구식 `내지`), 항·호·목, 타법(`「소득세법」 제X조`), 지시 인용(`법/영/규칙 제X조`), 별표·별지서식. 범위 인용은 조문 집합으로 펼쳐 중간 조문까지 포착.
- **인용 그래프 / 병행 매트릭스** — 사전 빌드해 런타임 LLM 호출 없이 즉시 역인용·병행 조회.
- **Claude 검토 레이어** — 신설 조문 검토 결과를 누락/판단필요/조치불요로 삼분류 + 종합 의견(보조).

---

## 입법예고 의견 분석 (CLI)

입법예고에 달린 의견을 **같은 취지끼리 묶어 건수 순으로 정렬**하고, 상위 X개 군집의
주요내용을 보고서로 뽑습니다. 종합부동산세법(1,600건+)·소득세법처럼 의견이 대량으로
달리는 입법예고에서 여론 지형을 한 장으로 보기 위한 도구입니다.

```bash
# 0) 사이트 구조 확인 (최초 1회) — 1페이지 원문 HTML을 저장
uv run python scripts/fetch_opinions.py --bill 87936 --probe

# 1) 수집 (요청 간격 1초, robots.txt 확인, 작성자 실명은 저장하지 않음)
uv run python scripts/fetch_opinions.py --bill 87936

#    크롤링이 막히면 — 브라우저에서 저장한 HTML/CSV로 대체
uv run python scripts/fetch_opinions.py --bill 87936 --from-files saved/*.html

# 2) 군집화·리포트
uv run python scripts/analyze_opinions.py --bill 87936 --law 종합부동산세법 --top 20
uv run python scripts/analyze_opinions.py --bill 87936 --top 20 --no-llm   # API 키 없이
```

산출물(`output/`): 보고서 `opinions-{bill}.md`, 군집 요약 `…-clusters.csv`,
전 건의 군집 배정 `…-members.csv`(판정 감사용).

**군집·건수는 결정적 레이어가 정하고, Claude는 상위 X개 군집의 문장 정리에만 관여합니다**
— 실행할 때마다 통계가 달라지지 않고, `--no-llm`이면 API 호출 없이 같은 구조의 리포트가
나옵니다. 자세한 내용·임계값 조정·사이트 개편 대응은
[docs/opinion-clustering.md](docs/opinion-clustering.md).

---

## 설치

Python 3.13+ 및 [uv](https://github.com/astral-sh/uv).

```bash
uv sync
```

## 환경 변수

프로젝트 루트에 `.env` (`.env.example` 참조):

```env
LAW_API_KEY=...            # 법제처 Open API 인증키 (필수)
OPENAI_API_KEY=sk-...      # 개정 초안 생성용 (보조 기능)
ANTHROPIC_API_KEY=...      # Claude 검토 레이어 · 병행 매트릭스 빌드용
# ENABLE_HWPX_OUTPUT=1     # HWPX 출력 활성화(기본 비활성화)
```

법제처 키 발급: [open.law.go.kr](https://open.law.go.kr) 회원가입 후 인증키 신청.

## 실행

```bash
uv run streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속. 탭: **1️⃣ 초안 작성 · 2️⃣ 인용·준용 확인 · 3️⃣ HWPX 출력(준비 중) · 🆕 신설 조문 검토**.

---

## 검증 (오프라인 테스트)

API 키 없이 파서·인용그래프·병행매트릭스·별표 등 핵심 로직을 검증합니다.

```bash
uv run python -m scripts.run_offline_tests
```

`push`/`pull_request` 시 GitHub Actions([offline-tests.yml](.github/workflows/offline-tests.yml))에서 동일 스위트를 실행합니다.

---

## 아키텍처 (요지)

```
TaxLawAmend/
├── app.py                      # Streamlit 진입점, 탭 구성·기능 플래그
├── config.py                   # API URL, 병행법령 매핑, 기능 플래그
├── core/
│   ├── citation_parser.py      # 인용·준용·범위·별표 파싱 (결정적 핵심)
│   ├── citation_graph.py       # 역인용 그래프 (사전 빌드 JSON 조회)
│   ├── parallel_matrix.py      # 병행 매트릭스 조회 (런타임 LLM 0회)
│   ├── article_relations.py    # 직접입력 → 연관 조문 4+1분류
│   ├── new_article_scanner.py  # 신설 조문 검토 (잔존 인용·프록시·별표)
│   ├── byeolpyo.py             # 별표 ↔ 조문 양방향 연관
│   ├── law_network.py          # 법령군 스코프·역인용 스캔
│   ├── llm_review.py           # Claude 검토 레이어 (삼분류)
│   ├── opinion_source.py       # 입법예고 의견 수집 (크롤링 + 파일 폴백)
│   ├── opinion_cluster.py      # 의견 군집화 (완전중복·근사중복·TF-IDF 코사인)
│   ├── opinion_tagging.py      # 관련 조문·찬반·쟁점 태깅 (citation_parser 재사용)
│   ├── opinion_summary.py      # 상위 군집 Claude 요약 (보조)
│   ├── amendment_agent.py      # 개정 초안 생성 (보조)
│   ├── hwpx_writer.py          # HWPX 생성 (준비 중)
│   └── law_api.py              # 법제처 Open API 클라이언트
└── ui/                         # 단계별 Streamlit UI
```

자세한 내용은 [docs/architecture.md](docs/architecture.md).

---

## 데이터 갱신 (법령 개정 시)

```bash
# 현행본 갱신 확인
uv run python scripts/check_law_freshness.py --update-manifest

# 인용 그래프 재빌드 (역인용·별표 — API 비용 없음)
uv run python scripts/build_law_citation_graph.py --all

# 병행 매트릭스 (0~2단계 무료 → 3단계 Claude Batches 약 $3)
uv run python scripts/build_parallel_matrix.py
uv run python scripts/build_parallel_candidates.py
uv run python scripts/adjudicate_parallel_pairs.py --submit
uv run python scripts/adjudicate_parallel_pairs.py --fetch
uv run python scripts/build_parallel_matrix.py
uv run python scripts/build_special_tax_links.py
```

---

## 내부자료 보호

심사·발표 전 개정안 등 내부 문서는 저장소·외부 서비스에 올리지 않습니다. 업로드 파일은 `data/uploads/`(gitignore)에만 저장되고, 골든 기대값 등 민감 자료도 저장소 밖으로 외부화되어 있습니다.

---

## 문서

| 파일 | 내용 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 전체 아키텍처·모듈 설계·구현 이력 |
| [docs/citation-parsing.md](docs/citation-parsing.md) | 인용 파싱 지원 패턴·한계·확장 |
| [docs/parallel-law-detection.md](docs/parallel-law-detection.md) | 병행법령 탐지 로직·한계·확장 |
| [docs/opinion-clustering.md](docs/opinion-clustering.md) | 입법예고 의견 수집·군집화·요약 파이프라인 |
| [docs/handoff-입법예고-의견분석.md](docs/handoff-입법예고-의견분석.md) | 위 도구의 작업 인계 노트 — 판단 근거·실측 결과·남은 작업 |
| [docs/manual-test-scenarios.md](docs/manual-test-scenarios.md) | 수동 테스트 시나리오·알려진 한계 |

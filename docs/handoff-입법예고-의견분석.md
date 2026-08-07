# 인계 노트 — 입법예고 의견 분석 도구

> 다른 세션에서 이 작업을 이어받기 위한 요약입니다. 대화 맥락은 넘어가지 않으므로
> **여기 있는 내용 + [opinion-clustering.md](opinion-clustering.md)가 전부**입니다.
> 설계 세부·튜닝 방법은 그쪽 문서에, "왜 그렇게 정했는지"는 이 문서에 있습니다.

| 항목 | 값 |
|------|-----|
| 브랜치 | `claude/legislative-opinion-sorter-gb79hj` |
| 커밋 | `a03fb4c` (파이프라인) → `4f7a59d` (쟁점별 합계 + 태깅 버그 수정) |
| 분기점 | `d5f64ce` (main, 이후 main 이동 없음) |
| 상태 | 오프라인 테스트 19/19 통과, 푸시 완료, PR 없음 |
| 작업 일자 | 2026-08-07 |

---

## 1. 무엇을 요청받았나

> "종합부동산세법 입법예고에 1,600건 넘는 의견이 달리고 있다. 소득세법도 의견이 많다.
> 특정 법개정안에 제기된 입법예고 의견을 **같은(유사한) 내용 위주로 소팅해서 의견수 기준
> 상위 X개의 주요내용을 정리해 주는 도구**를 만들 수 있나?"

대상 URL: `https://opinion.lawmaking.go.kr/gcom/ogLmPp/87936/myOpn?opnOpYn=Y&`

계획 단계에서 사용자가 고른 세 가지 (이후 작업의 전제):

| 선택지 | 결정 |
|--------|------|
| 수집 방식 | **크롤러 + 파일 폴백 이중화** |
| 유사도 방식 | **결정적 군집화 + 상위 군집만 Claude 요약** |
| 산출물 | **CLI 리포트 (MD/CSV)** — Streamlit 탭은 범위 밖 |

---

## 2. 만든 것

```
[수집]  scripts/fetch_opinions.py   ─► data/opinions/{bill}.json   (gitignore)
[정규화] core/opinion_normalize.py
[군집화] core/opinion_cluster.py
[태깅]  core/opinion_tagging.py     ─► citation_parser 재사용
[요약]  core/opinion_summary.py     ─► 상위 X개 군집만 Claude
[출력]  scripts/analyze_opinions.py ─► output/opinions-{bill}.md + CSV 2종
```

| 파일 | 역할 |
|------|------|
| `core/opinion_source.py` | 수집 어댑터. XPath 설정 기반 파싱 + generic 폴백 + CSV/JSON, 작성자 마스킹, robots.txt, 페이지 반복 감지 |
| `core/opinion_normalize.py` | 정규화·문자 3-gram·세법 약칭 통일·상투구 제거 |
| `core/opinion_cluster.py` | 완전중복 → MinHash/LSH → TF-IDF 코사인 → union-find → 적응형 재분할 |
| `core/opinion_tagging.py` | 관련 조문·찬반·요구사항·쟁점 태그 |
| `core/opinion_summary.py` | 상위 군집 Claude structured output 요약 + 캐시 |
| `core/opinion_report.py` | Markdown 보고서 + clusters/members CSV + 쟁점별 합계 |
| `scripts/{fetch,analyze}_opinions.py` | CLI 2종 |
| `scripts/test_opinion_{source,cluster}.py` | 오프라인 테스트 (스위트 등록됨) |
| `data/opinion-fixtures/` | 합성 픽스처 3종 |
| `docs/opinion-clustering.md` | 설계·튜닝·한계 문서 |

기존 코드 변경은 4곳뿐입니다: `.gitignore`(`data/opinions/` 추가), `README.md`(섹션),
`core/llm_review.py`(`structured_call()` 공개 래퍼 추가), `scripts/run_offline_tests.py`(모듈 2개 등록).

---

## 3. 왜 이렇게 만들었나 — 판단 근거

### 통계는 결정적으로, 문장만 LLM으로
저장소 제1원칙과 같은 이유입니다. 실행할 때마다 건수가 달라지면 보고자료로 못 씁니다.
군집·건수는 규칙과 유사도가 정하고, Claude는 **이미 확정된 군집을 읽을 문장으로 옮기기만**
합니다. 그래서 요약이 틀려도 통계는 안 흔들리고, `--no-llm`이면 API 키 없이 같은 구조의
리포트가 나옵니다. 난수를 안 쓰고 파이썬 내장 `hash()` 대신 `zlib.crc32`를 쓰는 것도
같은 이유입니다(내장 hash는 프로세스마다 시드가 달라 결과가 흔들림).

### 완전 중복을 가장 먼저 접는다
입법예고 의견은 복붙 캠페인이 절반을 차지하는 게 정상입니다. 먼저 접으면 이후 단계의 N이
급감합니다(실측: 2,000건 → 고유 42종 → 0.08초). IDF도 **변형 기준**으로 셉니다 — 복붙
800건을 800으로 세면 그 문구의 idf가 0에 수렴해 정작 가장 큰 덩어리를 구분하지 못합니다.

### 임베딩을 쓰지 않았다
표현이 다른 같은 주장을 더 잘 묶겠지만, 재현성이 떨어지고 1,600건×N회 API 비용이 듭니다.
결정적 결과를 우선했습니다. 필요해지면 `opinion_cluster`에 백엔드를 추가하는 형태로 확장
가능합니다.

### 상투구 제거에 안전장치를 두 겹 걸었다
"자주 나오는 문장"을 그냥 지우면 복붙 의견의 **핵심 주장이 사라집니다.** 그래서 ①실질
신호(조문 인용·숫자·주장 어휘)가 있는 문장은 df가 아무리 높아도 상투구로 안 보고,
②제거 결과가 비면 원문을 그대로 돌려줍니다.

### 과병합은 임계값이 아니라 적응형 재분할로 막는다
"전체의 35%를 넘으면서 응집도 0.55 미만"인 군집만 임계값을 올려 재분할합니다. 응집도
조건이 있어서 진짜 큰 단일 쟁점("종부세 폐지" 800건)은 안 쪼개집니다.

### 개인정보는 코드로 강제
작성자 실명을 아예 저장하지 않습니다(수집 시점 마스킹 + 복원 불가 해시). 어떤 필드로도
실명이 새지 않는지 테스트가 검사합니다. 수집 원문은 `data/opinions/`(gitignore)에만 두고,
픽스처는 합성 데이터만 커밋했습니다.

---

## 4. 실측으로 확인한 것

합성 1,670건(실제 분포 특성을 흉내내고 **정답 테마 11종을 알고** 생성)으로 검증했습니다.

### 임계값 0.45가 맞다 — 데이터로 확인
| 임계값 | 취지 혼입 | 비고 |
|-------:|---------:|------|
| 0.30 | 12건 | 혼입 시작 |
| 0.35~0.50 | 0건 | **결과 사실상 동일** |

→ **임계값을 내려도 "표현이 완전히 다른 같은 주장"은 안 붙고 순도만 나빠집니다.**
이 간극은 쟁점별 합계로 메웁니다(아래).

### 쟁점별 합계를 추가한 이유
1주택 폐지 요구 400건이 표현 차이로 **5개 군집으로 분산**됐습니다. 건수 순 상위 목록만
보면 같은 주제가 여러 번 나와 실제 규모를 놓칩니다. 쟁점 태그 기준 의견 단위 집계를
리포트에 함께 실어 해결했습니다 — `1세대 1주택 406건`으로 복원(정답 400건).

군집마다 대표 쟁점 하나를 고르는 방식도 시도했다가 버렸습니다. `1세대 1주택`과 `이중과세`가
동점일 때 선택이 자의적이 되어 **오히려 주제를 쪼갰기** 때문입니다(305 + 62로 분리됨).

### 태깅 부분일치 버그 (수정 완료)
`중과`가 **이**중과세에 부분일치해 1주택 폐지 의견 305건이 "다주택 중과"로 오태깅됐습니다.
한국어는 어절 경계가 없어 짧은 표면형이 다른 단어 속에 그대로 들어갑니다. 앞뒤가 붙어도
뜻이 유지되는 형태(`중과세율`, `중과 유지`)만 남기고 회귀 테스트를 추가했습니다.
**쟁점 사전을 확장할 때 같은 함정을 반드시 확인하세요.**

### 성능
| 코퍼스 | 시간 |
|--------|------|
| 1,670건 / 고유 231종 (실제와 가까움) | 1.6초 |
| 2,000건 / 고유 42종 | 0.08초 |
| 1,600건 / 전부 고유 (최악) | 4.7초 |
| 5,000건 / 전부 고유 (최악) | 38초 |

전부 고유한 경우가 최악이고 대략 제곱으로 증가합니다.

---

## 5. 아직 안 된 것 / 다음 작업

### (1) 실사이트 셀렉터 확정 — **가장 먼저 할 일**
작업 세션의 egress 프록시가 `opinion.lawmaking.go.kr`·`law.go.kr` 등 go.kr 도메인을
전부 차단해(CONNECT 403) **실제 DOM을 한 번도 보지 못했습니다.** `DEFAULT_SELECTORS`는
추정치입니다. 네트워크가 되는 환경에서:

```bash
uv run python scripts/fetch_opinions.py --bill 87936 --probe
#   → data/opinions/_probe/87936-page1.html 확인
#   → data/opinion-selectors.json 에 XPath 작성 (예시는 opinion-clustering.md)
uv run python scripts/fetch_opinions.py --bill 87936 --pages 3   # 소량 검증 먼저
uv run python scripts/fetch_opinions.py --bill 87936             # 전량
uv run python scripts/analyze_opinions.py --bill 87936 --law 종합부동산세법 --top 20
```

페이지 파라미터명(`--page-param`, 기본 `pageIndex`)도 실제 사이트에서 확인이 필요합니다.
틀리면 매 페이지가 같은 내용을 돌려주는데, 새 의견이 0건이면 즉시 멈추도록 해 뒀습니다.

### (2) Claude 요약 경로 미검증
`ANTHROPIC_API_KEY`가 없어 `core/opinion_summary.py`를 **한 번도 실행하지 못했습니다.**
코드 경로(스키마·캐시·모델 폴백)는 `core/llm_review.py`의 검증된 관용구를 그대로 따르지만,
실제 호출은 확인 안 됐습니다. 키 설정 후 `--top 3`으로 한 번 돌려 스키마와 캐시 동작을
확인하세요. 실패해도 결정적 라벨로 리포트는 완성됩니다.

### (3) 합성 코퍼스 생성기 — 저장소에 없음
위 실측에 쓴 생성기(`make_demo_corpus.py`)는 작업 세션의 임시 폴더에만 있었고 **커밋하지
않았습니다.** 실제 수집 전 도구 시험이나 임계값 재보정에 유용하므로, 필요하면 다시 만들어야
합니다. 사양: 테마 11종(정답 라벨 포함) × 복붙 비율 35~55% × 표현 변형 2~5종 + 인사말 40% +
롱테일 120건, 시드 고정.

### (4) 범위 밖으로 합의한 것
- **Streamlit 탭** — CLI 확정 후 별건
- **HWPX 출력** — 기능 플래그(`ENABLE_HWPX_OUTPUT`)로 비활성 상태
- **임베딩 기반 의미 군집** — 재현성 우선으로 미채택

### (5) 정확도를 더 올리고 싶다면
- `ISSUE_LEXICON`(쟁점 사전)에 세목별 항목 추가 — 소득세법 분석 시 특히 필요
- `ABBREVIATIONS`(약칭 사전)에 표면형 추가 — 군집이 갈릴 때 임계값보다 효과적
- 둘 다 부분일치 함정을 확인하고 테스트를 추가할 것

---

## 6. 검증 방법

```bash
uv run python -m scripts.run_offline_tests            # 전체 (신규 2개 포함)
uv run python -m scripts.test_opinion_cluster         # 군집 purity·중복접기·결정성
uv run python -m scripts.test_opinion_source          # 파싱·마스킹·폴백

# 픽스처로 엔드투엔드 (네트워크·API 키 불필요)
uv run python scripts/analyze_opinions.py --bill T --law 종합부동산세법 --top 5 --no-llm \
  --from-files data/opinion-fixtures/sample-opinions.csv
```

테스트가 고정하고 있는 계약 4가지: ①같은 취지가 같은 군집에 모이고 다른 취지가 안 섞인다
②완전 중복이 접히고 건수가 보존된다 ③인사말만 같은 의견이 갈라진다 ④입력 순서를 바꿔도
결과가 같다.

---

## 7. 병합 (검증 완료)

`main`은 분기 이후 움직이지 않았고, `feature/renumber-omission-scan`과 실제로 병합해
확인했습니다: **충돌 0건, 오프라인 테스트 20/20 통과.** 겹치는 파일은 `.gitignore`,
`core/llm_review.py`, `scripts/run_offline_tests.py` 3개인데 서로 다른 줄이라 자동 병합됩니다.

```bash
git fetch origin
git merge origin/claude/legislative-opinion-sorter-gb79hj
uv run python -m scripts.run_offline_tests
```

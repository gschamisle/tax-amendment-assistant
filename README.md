# 세법개정 AI 어시스턴트

대한민국 재정경제부 세제실 업무를 위한 법령 개정 자동화 도구.
법제처 Open API로 현행 조문을 조회하고 OpenAI API 기반으로 개정 초안을 작성한 뒤 HWPX 문서로 출력한다.

---

## 목차

1. [기능 개요](#기능-개요)
2. [설치](#설치)
3. [환경 변수](#환경-변수)
4. [실행](#실행)
5. [3단계 워크플로우](#3단계-워크플로우)
6. [아키텍처](#아키텍처)
7. [알려진 한계 및 확장 포인트](#알려진-한계-및-확장-포인트)
8. [문서](#문서)

---

## 기능 개요

| 단계 | 기능 |
|------|------|
| **1단계** | 법령 검색 → 개정할 조문 선택 → OpenAI API 기반 개정 초안 생성 |
| **1단계** | 항별 변경 확인·선택, 연관 항 검토 제안, 부칙 적용 기준·조문별 적용례 자동 작성 |
| **1단계** | 병행 법령 동일 취지 검사 (법인세법 ↔ 소득세법 및 하위법령 등), 병행법령 초안 항 번호 자동 보정 |
| **2단계** | 개정안 내 인용·준용 규정 파싱 및 링크 제공 |
| **2단계** | 조문 번호 밀림 검사 (조문 신설 시 기존 인용 번호 영향) |
| **2단계** | 역방향 인용 검사 (이 조문을 인용하는 다른 조항 탐색) |
| **3단계** | 신·구조문대비표 미리보기 |
| **3단계** | HWPX 파일 생성 및 다운로드 (현행 빨간색, 개정안 파란색) |

---

## 설치

Python 3.13+ 및 [uv](https://github.com/astral-sh/uv) 사용.

```bash
# 의존성 설치
uv sync
```

주요 의존성:
- `streamlit` — UI 프레임워크
- `openai` — OpenAI API
- `requests` — 법제처 Open API 호출
- `python-hwpx` — HWPX 문서 생성

---

## 환경 변수

프로젝트 루트에 `.env` 파일 생성 (`.env.example` 참조):

```env
OPENAI_API_KEY=sk-...          # OpenAI API 키
LAW_API_KEY=your_key_here      # 법제처 Open API 인증키
```

**법제처 Open API 키 발급**: [https://open.law.go.kr](https://open.law.go.kr) 회원가입 후 인증키 신청.

---

## 실행

```bash
uv run streamlit run app.py

# 또는
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

---

## 3단계 워크플로우

### 1단계: 개정 조문 초안 작성

1. **법령 검색**: 법령명 입력 후 검색 (엔터 또는 검색 버튼).
2. **조문 선택**: 법령 선택 → "조문 목록 불러오기" → 개정할 조문 선택.
   - 이미지(세율표)가 많은 법령은 첫 로딩 시 20~60초 소요. 이후 1시간 캐시.
3. **개정 요강 입력**: 개정 내용 텍스트로 입력 (예: "법인세율을 현행 20%에서 19%로 인하").
4. **부칙 적용 기준 선택**: 사업연도 / 과세기간 / 신고 / 지급·수령 / 양도·취득 / 공급 / 발생·거래 등.
5. **GPT 초안 생성**: OpenAI API가 개정지시문, 현행/개정안 대비표, 부칙 초안 생성.
   - 현행: 미변경 항 → `① (생략)`, 변경 항 → 삭제 문구 `<del>` 표시
   - 개정안: 미변경 항 → `① (현행과같음)`, 변경 항 → 신규 문구 `<u>` 표시
   - 부칙: 제1조(시행일) + 제2조~(개정조문 제목에 관한 적용례) 형식
6. **검토 및 수정**:
   - 변경된 항별 체크박스로 적용 여부 선택.
   - 연관 항 검토 제안 확인.
   - 현행/개정안 텍스트 직접 수정 가능.
7. **병행 법령 검사**: "병행 법령 검사" 클릭 → 코드 매핑·키워드 후보 검색·OpenAI 의미 판단을 조합해 병행 개정 필요 조문 탐색.
   - 법인세법/소득세법 및 시행령·시행규칙 등 관련·하위 법령군을 함께 검토.
   - 병행 법령 초안 생성 시 해당 법령의 실제 항 번호로 개정지시문 자동 보정.

### 2단계: 인용·준용 규정 확인

1. **인용 규정 파싱**: 개정안 내 `제X조제Y항` 형태 인용을 regex로 추출.
   - 본법 내부 인용: 법제처 원문 링크 포함 표로 표시.
   - 타법 인용: `「소득세법」 제XX조` 형태 별도 표시.
2. **조문 번호 밀림 검사**: 조문 신설 시 기존 인용 번호에 영향받는 조항 탐색.
3. **역방향 인용 검사**: 개정 조문을 인용하는 동일 법령 또는 관련·하위 법령군의 다른 조항 탐색.

### 3단계: HWPX 출력

1. **미리보기**: 개정지시문, 신·구조문대비표, 부칙 확인.
2. **HWPX 생성**: 클릭 한 번으로 `.hwpx` 파일 생성.
   - 현행 삭제 문구: **빨간색 텍스트** (PDF 표준)
   - 개정안 신규 문구: **파란색 텍스트**
   - 미변경 텍스트: 대시(`- - - -`) 처리, 한글 시각 너비(2단위) 기준 정렬
3. **다운로드**: 메인 법령 및 병행 법령별 HWPX 개별 다운로드.

---

## 아키텍처

```
mofe_2nd/
├── app.py                    # Streamlit 진입점, 탭 구성
├── config.py                 # API URL, 병행법령 매핑(PARALLEL_LAWS)
├── core/
│   ├── amendment_agent.py    # OpenAI API 개정 초안 생성, 섹션 파서
│   ├── citation_parser.py    # 인용·준용 규정 regex 파싱
│   ├── cross_ref_checker.py  # 병행법령 코드 매핑·키워드 후보 검색·의미 매칭
│   ├── hwpx_writer.py        # HWPX 테이블 생성, 색상 charPr 주입
│   └── law_api.py            # 법제처 Open API 클라이언트, OCR 캐시
├── ui/
│   ├── stage1_draft.py       # 1단계 UI
│   ├── stage2_crossref.py    # 2단계 UI
│   └── stage3_output.py      # 3단계 UI, HWPX 파일 생성
└── docs/                     # 참고 문서 및 기술 문서
```

자세한 내용은 [docs/architecture.md](docs/architecture.md) 참조.

---

## 알려진 한계 및 확장 포인트

### 인용 파싱

현재 `전항`, `다음 항`, `단서에 따라`, `이 조에서` 같은 패턴은 탐지하지 않는다.
실제로 못 찾는 원문이 생기면 즉시 패턴 추가 가능.
→ [docs/citation-parsing.md](docs/citation-parsing.md) 참조.

### 병행 법령 탐지

법인세법·소득세법의 대표 병행 조문은 코드 매핑으로 우선 탐지하고, 그 밖의 병행 후보는 키워드·동의어 필터와 OpenAI 의미 판단을 함께 사용한다.
탐지 못하는 법령이 있으면 `config.py`의 `PARALLEL_LAWS` 또는 `core/cross_ref_checker.py`의 병행 조문 힌트에 추가하면 됨.
→ [docs/parallel-law-detection.md](docs/parallel-law-detection.md) 참조.

---

## 문서

| 파일 | 내용 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 전체 아키텍처, 모듈별 설계 결정 사항, 구현 이력 |
| [docs/citation-parsing.md](docs/citation-parsing.md) | 인용 파싱 지원 패턴, 한계, 확장 방법 |
| [docs/parallel-law-detection.md](docs/parallel-law-detection.md) | 병행법령 탐지 로직, 한계, 확장 방법 |
| [docs/manual-test-scenarios.md](docs/manual-test-scenarios.md) | 기능별 수동 테스트 시나리오 및 알려진 한계 |
| [docs/corporate-income-tax-parallel-manual.md](docs/corporate-income-tax-parallel-manual.md) | 법인세↔소득세·부가세·조특법 병행개정 매뉴얼 |
| [docs/reference-materials.md](docs/reference-materials.md) | Git 제외 로컬 PDF·CSV 참고 자료 |
| [docs/법령한글주소사용방법.md](docs/법령한글주소사용방법.md) | 법제처 한글 URL 생성 규칙 |

### 법령 현행본·조특법 연결 갱신 (연 1회 권장)

```bash
uv run python scripts/check_law_freshness.py
uv run python scripts/check_law_freshness.py --update-manifest
uv run python scripts/build_special_tax_links.py
```

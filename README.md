# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색할 수 있는지 검증하는 기술 PoC입니다.

## 1. 프로젝트 목적

실제 DEMIS 연계 개발에 앞서 다음을 검증합니다.

- Legacy 스타일 물리명(예: `TB_LAB_RST`, `EXM_CD`)만으로도 Comment/관계 메타데이터를 활용해 Schema를 찾을 수 있는가
- 다단계 FK 관계(3~5+ JOIN)를 포함한 스키마에서 의미 검색이 가능한가
- CPU-only / On-premise 환경에서 Embedding + pgvector 기반 Hybrid Search가 현실적인가

## 2. PoC 범위

최종 목표 흐름:

```text
Test Medical DB
→ Schema Analyzer
→ Schema Catalog
→ Embedding Pipeline
→ PostgreSQL + pgvector
→ Semantic / Hybrid Search API
→ Streamlit Frontend
```

**이번 저장소의 현재 구현은 Step 1만 포함합니다.**

## 3. 현재 구현 Step

**Step 1 — Foundation + Mock Medical DB**

포함:

- Docker Compose 기반 로컬 개발환경
- DEMIS를 모사한 `medical_demo` Mock 의료 DB (20+ tables, PK/FK, Comment, Index, Seed)
- 향후 Catalog용 `schema_catalog` DB 부트스트랩
- FastAPI Health Check (`medical_demo` / `schema_catalog` 연결 확인)
- Streamlit 기본 상태 화면
- pytest 기반 기초 검증

포함하지 않음:

- LLM / OpenAI API
- 자연어 → SQL 생성
- Embedding / Semantic Search / pgvector 검색
- Schema Analyzer API

## 4. 전체 Architecture (Step 1)

```text
┌────────────┐  Compose DNS :8000  ┌────────────┐
│  frontend  │ ──────────────────► │  backend   │
│ (Streamlit)│                     │  (FastAPI) │
└────────────┘                     └─────┬──────┘
                                         │
                    Compose DNS :5432    │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                                                     ▼
     ┌────────────────┐                                   ┌─────────────────┐
     │   medical-db   │                                   │   catalog-db    │
     │ medical_demo   │                                   │ schema_catalog  │
     │ (+ init seed)  │                                   │ (pgvector 가능) │
     └────────────────┘                                   └─────────────────┘
```

컨테이너 간 연결은 Docker Compose **service DNS**를 사용합니다.

- `backend → medical-db:5432`
- `backend → catalog-db:5432`
- `frontend → backend:8000`

호스트 published port(`5433`, `5434`, `8000`, `8501`)는 로컬 접속/디버깅용입니다.
## 5. 기술스택

| 영역 | 기술 |
|------|------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x, psycopg |
| Database | PostgreSQL 16, (catalog) pgvector 이미지 |
| Frontend | Streamlit |
| Infra | Docker, Docker Compose |
| Test | pytest |

제약:

- 생성형 LLM / 외부 LLM API 미사용
- CPU-only 전제
- 국방망 On-premise 실행을 고려한 로컬 Compose 구조

## 6. 프로젝트 디렉터리 구조

```text
demis-schema-search-poc/
  backend/
    app/
      api/
      core/
      db/
      models/
      services/
    tests/
    Dockerfile
    requirements.txt
  frontend/
    app.py
    Dockerfile
    requirements.txt
  database/
    medical_demo/
      Dockerfile     # Postgres + init seed
      init/          # schema / comments / indexes
      seed/          # deterministic seed script
    schema_catalog/
      init/
  scripts/
  docker-compose.yml
  .env.example
  README.md
```

## 7. Docker Compose 실행 방법

### 사전 준비

- Docker Desktop (Windows/macOS) 또는 Docker Engine + Compose (Linux)
- CPU-only 환경에서 실행 가능

### 실행

```bash
cp .env.example .env
docker compose up --build
```

또는:

```bash
cp .env.example .env
bash scripts/start.sh
```

최초 기동 시:

1. `medical-db` 스키마/Comment/Index 초기화 후 deterministic seed 적재
2. `catalog-db` 부트스트랩
3. `backend` / `frontend` 기동
종료:

```bash
docker compose down
```

볼륨까지 삭제(재초기화):

```bash
docker compose down -v
```

## 8. medical_demo 설명

`medical_demo`는 DEMIS를 대신하는 **Mock 의료 DB**입니다.

목적:

- 직관적이지 않은 Legacy 물리명
- 다단계 관계 구조
- 한국어 COMMENT 메타데이터
- 실제 PK/FK/Index 메타데이터

를 제공하여 이후 Schema Analyzer / Semantic Search 품질을 검증합니다.

분석 대상 DB(`medical_demo`)와 시스템 관리 DB(`schema_catalog`)는 분리되어 있습니다.

## 9. 주요 Table과 관계

총 **24개 Table**을 구성합니다.

### Master

- `TB_PT_MST` 환자
- `TB_DEPT_MST` 진료과
- `TB_PROVIDER` 의료진
- `TB_WARD_MST` 병동
- `TB_CODE_MST` 공통코드
- `TB_DGN_CD_MST` 진단코드
- `TB_LAB_MST` 검사항목
- `TB_LAB_REF` 검사기준치
- `TB_DRUG_MST` 약품
- `TB_IMG_MST` 영상검사항목
- `TB_PROC_MST` 처치/시술
- `TB_DOC_TYPE` 문서유형

### Transaction

- `TB_ENC_HIST` Encounter
- `TB_ADM_HIST` 입원
- `TB_DGN_HIST` 진단이력
- `TB_PROC_HIST` 처치이력
- `TB_ORD_HDR` / `TB_ORD_DTL` 오더
- `TB_LAB_ORD` / `TB_LAB_RST` 검사오더/결과
- `TB_MED_ORD` 처방
- `TB_IMG_ORD` / `TB_IMG_RPT` 영상오더/판독
- `TB_CLN_DOC` 임상문서

### 대표 다단계 흐름

1. 검사결과  
   `TB_PT_MST → TB_ENC_HIST → TB_ORD_HDR → TB_LAB_ORD → TB_LAB_RST → TB_LAB_MST`
2. 처방  
   `TB_PT_MST → TB_ENC_HIST → TB_ORD_HDR → TB_MED_ORD → TB_DRUG_MST`
3. 영상판독  
   `TB_PT_MST → TB_ENC_HIST → TB_IMG_ORD → TB_IMG_RPT → TB_IMG_MST`
4. 임상문서  
   `TB_PT_MST → TB_ENC_HIST → TB_CLN_DOC → TB_DOC_TYPE`
5. 입원  
   `TB_PT_MST → TB_ENC_HIST → TB_ADM_HIST → TB_WARD_MST`

검사 Master에는 AST/ALT/GGT/ALP/Total Bilirubin, Glucose/FBS/HbA1c, Creatinine/eGFR/BUN을 포함합니다.  
“간수치” 같은 개념은 단일 컬럼명이 아니라 검사코드 Master를 통해 표현됩니다.

## 10. Health Check 방법

Backend:

```bash
curl http://localhost:8000/health
```

예상 응답 예:

```json
{
  "status": "ok",
  "backend": "ok",
  "medical_db": "ok",
  "catalog_db": "ok",
  "step": "Step 1 - Foundation / Mock Medical DB",
  "app_name": "DEMIS Schema Semantic Search PoC"
}
```

Frontend: http://localhost:8501

## 11. Test 실행 방법

Compose로 DB가 떠 있는 상태에서:

```bash
# backend 컨테이너에서 실행
docker compose exec backend pytest -q

# 또는 호스트에서 (의존성 설치 후)
bash scripts/run_tests.sh
```

검증 항목:

- Backend Health Check
- medical_demo / schema_catalog 연결
- 주요 Table 생성
- PK/FK 생성
- Seed Data 존재
- Patient → Encounter → Lab Order → Lab Result → Lab Master JOIN

## 12. 향후 개발 Step

| Step | 내용 |
|------|------|
| **Step 1** | Foundation + Mock Medical DB *(현재)* |
| **Step 2** | Schema Analyzer + Schema Catalog |
| **Step 3** | CPU-only Embedding Pipeline + PostgreSQL/pgvector |
| **Step 4** | Semantic / Keyword Hybrid Search + FK Relation Expansion |
| **Step 5** | Streamlit Schema Explorer / Natural Language Search UI |
| **Step 6** | 정확도 평가 및 기술검증 (Top-1, Recall@3/5, Relation Accuracy, Latency, Indexing Time, Schema Change Detection) |

## 환경변수

`.env`는 Git에 포함하지 않습니다. `.env.example`을 복사해 사용하세요.

주요 변수:

- `MEDICAL_DB_*` — Mock 의료 DB
- `CATALOG_DB_*` — Schema Catalog DB
- `SEED_PATIENT_COUNT` / `SEED_RANDOM_SEED` — Seed 제어
- `BACKEND_URL` — Frontend → Backend 주소

## License

PoC / internal evaluation use.

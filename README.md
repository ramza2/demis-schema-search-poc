# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색할 수 있는지 검증하는 기술 PoC입니다.

## 1. 현재 Step

**Step 2 — Schema Analyzer + Schema Catalog**

분석 대상 의료 DB(`medical_demo`)에 연결하여 Schema Metadata를 자동 수집하고,
`schema_catalog` DB에 구조화 저장합니다.

이번 Step에서는 Embedding / pgvector / Semantic Search / LLM을 구현하지 않습니다.

## 2. Schema Analyzer Architecture

```text
medical-db (medical_demo)
   │
   │ metadata SELECT only
   ▼
PostgreSQLSchemaInspector
   ↓
SchemaAnalysisService
   ↓
Normalize / Fingerprint
   ↓
CatalogWriter (upsert)
   ↓
catalog-db (schema_catalog)
```

- Source DB(`medical_demo`): Schema Metadata 조회만 수행 (INSERT/UPDATE/DELETE/DDL 금지)
- Catalog DB(`schema_catalog`): 분석 결과 Read/Write
- DBMS Adapter는 `SchemaInspector` 인터페이스로 분리되어 있으며, 현재는 PostgreSQL 구현만 제공합니다.

## 3. Source DB vs Catalog DB

| 구분 | medical_demo | schema_catalog |
|------|--------------|----------------|
| 역할 | 분석 대상 Mock 의료 DB | Schema Catalog 저장소 |
| Analyzer 권한 | SELECT(metadata) only | INSERT/UPDATE |
| Password 저장 | 환경변수만 사용 | Catalog Table에 평문 저장 금지 |

## 4. 수집 Metadata

- Database / Schema / 분석 실행시간
- Table: schema, name, type, comment
- Column: ordinal, name, type, length/precision/scale, nullable, default, comment
- Primary Key / Unique Constraint (composite 순서 포함)
- Foreign Key (composite mapping 포함)
- Index: name, unique, method, definition, columns

Search Enrichment(`searchable_text`, synonym, embedding 등)는 생성하지 않습니다.
Comment를 AI/Rule로 보강하지 않으며, 대상 DB에서 읽은 원본을 보존합니다.

## 5. Catalog 데이터 모델

| Table | 역할 |
|-------|------|
| `catalog_source` | 분석 대상 Source 등록(비민감 연결 메타만) |
| `catalog_analysis_run` | 분석 실행 이력 |
| `catalog_table` | Table 메타 + fingerprint / active |
| `catalog_column` | Column 메타 + PK/Unique flag |
| `catalog_relation` | FK Relationship |
| `catalog_relation_column` | Composite FK column mapping |
| `catalog_index` | Index 메타 |
| `catalog_index_column` | Index column 순서 |

Migration은 PoC 규모를 고려해 **init SQL + ORM `create_all` bootstrap**을 사용합니다.
Alembic은 도입하지 않았습니다(향후 모델 변경이 잦아지면 재검토).

## 6. API

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/schema/analyze` | medical_demo Schema 분석 후 Catalog 적재 |
| GET | `/api/v1/schema/runs` | 최근 분석 실행 이력 |
| GET | `/api/v1/schema/runs/{run_id}` | 분석 실행 상세 |
| GET | `/api/v1/schema/tables` | Catalog Table 목록 (`schema_name`, `active`, `name`) |
| GET | `/api/v1/schema/tables/{table_id}` | Table 상세(Column/PK/FK/Index/관계) |
| GET | `/health` | Backend / DB 연결 상태 |

분석 실행 예:

```bash
curl -X POST http://localhost:8000/api/v1/schema/analyze
```

응답 예:

```json
{
  "run_id": 1,
  "status": "SUCCESS",
  "source": "medical_demo",
  "schema": "public",
  "tables": 24,
  "columns": 180,
  "relations": 50,
  "indexes": 40,
  "schema_fingerprint": "...",
  "started_at": "...",
  "finished_at": "..."
}
```

## 7. Credential 관리 원칙

- Password는 Catalog Table에 저장하지 않습니다.
- Password는 API Response / 로그 / 예외 메시지에 노출하지 않습니다.
- DB Connection URL 전체를 로그로 남기지 않습니다.
- Source 접속정보는 환경변수(`MEDICAL_DB_*`, `CATALOG_DB_*`)를 사용합니다.

## 8. Docker Compose 실행

```bash
cp .env.example .env
docker compose up --build
```

서비스:

- `medical-db` :5433 (host debug)
- `catalog-db` :5434
- `backend` :8000
- `frontend` :8501

컨테이너 간 연결은 Compose service DNS를 사용합니다.

## 9. 테스트

```bash
docker compose exec backend pytest -q
# 또는
bash scripts/run_tests.sh
```

검증 항목:

- Step 1 기존 Health / PK/FK / Seed / Comment 테스트
- Schema Inspector Table/Column/PK/FK/Index 수집
- Catalog 적재 및 Idempotency
- Fingerprint 안정성
- Analysis Run / Table Detail API
- Credential 비노출

## 10. 현재 미구현 범위

- sentence-transformers / BGE-M3 / Embedding
- pgvector / vector column / cosine similarity
- Semantic / Keyword Hybrid Search
- Synonym / Query Expansion
- Relation Expansion 검색
- LLM / 자연어 → SQL / Dynamic SQL
- Schema Change Diff UI / 알림
- Streamlit Schema Explorer (Step 5)

## 11. 이후 Step 3 계획

CPU-only Embedding Pipeline + PostgreSQL/pgvector:

1. Catalog Metadata 기반 searchable text 생성(원본 Comment 보존 + 파생 필드 분리)
2. CPU Embedding 모델 로컬 적재
3. `schema_catalog`에 vector 컬럼/인덱스 추가
4. Embedding batch job 및 재분석 시 갱신 전략

## 12. 전체 PoC Roadmap

| Step | 내용 | 상태 |
|------|------|------|
| 1 | Foundation + Mock Medical DB | 완료 |
| 2 | Schema Analyzer + Schema Catalog | **현재** |
| 3 | CPU-only Embedding + pgvector | 예정 |
| 4 | Hybrid Search + FK Expansion | 예정 |
| 5 | Streamlit Schema Explorer | 예정 |
| 6 | 정확도 평가 / Schema Change Detection | 예정 |

## License

PoC / internal evaluation use.

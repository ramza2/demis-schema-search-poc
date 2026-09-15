# DEMIS Schema Semantic Search PoC

관계구조가 복잡한 의료 DB Schema를 자동 분석·임베딩하여, 자연어로 관련 Table / Column / Relationship을 검색하고,
Gold Set 기반 정량지표로 재현 가능한 평가를 수행하는 기술 PoC입니다.

## 1. 현재 Step

**Step 5 — Gold Set 기반 Schema Search 정량평가 자동화**

Step 1~4.1의 Search Pipeline을 **Evaluation Baseline으로 고정**한 뒤,
Gold Query Set으로 Semantic / Keyword / Hybrid를 자동 실행하고
Top-1 / Hit@K / Mean Recall@K / MRR / Latency를 산출합니다.

- 검색 알고리즘을 평가 결과에 맞춰 튜닝하지 않습니다.
- 자연어 → SQL / 생성형 LLM은 구현하지 않습니다.

## 2. Search Baseline (Freeze)

| Item | Value |
|------|-------|
| Embedding | BAAI/bge-m3, dim=1024 (local `bge_m3` or remote `openai_compatible`) |
| Semantic | pgvector exact cosine |
| Keyword | PostgreSQL FTS/token |
| Hybrid | RRF K=60 |
| Terminology | `backend/app/resources/medical_terms.json` |
| Relation | FK BFS max hop 2 |
| LLM / NL→SQL | None |

### Embedding provider 구성

**로컬 모델**

```bash
EMBEDDING_PROVIDER=bge_m3
EMBEDDING_MODEL_NAME=BAAI/bge-m3
EMBEDDING_MODEL_PATH=/models/local/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_NORMALIZE=true
```

**공용 OpenAI-compatible API (ALZI)**

```bash
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_URL=https://alzi-embedding.openlink.kr
EMBEDDING_API_KEY=
EMBEDDING_API_TIMEOUT_SECONDS=60
EMBEDDING_MODEL_NAME=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_NORMALIZE=true
```

문서 Embedding과 Query Embedding은 동일 provider / `model_key`를 사용합니다.
원격 API URL은 `model_key`에 포함되지 않습니다.

## 3. Evaluation 목적

생성형 LLM 없이 Schema Metadata + BGE-M3 + Keyword + Terminology + FK 정보가
Schema Discovery에서 어느 정도 정확도를 보이는지 **재현 가능한 정량지표**로 검증합니다.

## 4. Gold Dataset

**Source of Truth:** `backend/evaluation/gold_schema_queries.json`

- 약 45 Query
- Categories: `clinical_natural_language`, `paraphrase`, `schema_semantic`, `physical_identifier`, `ambiguous`, `relation`
- Identity 형식: `public.tb_lab_rst`, `public.tb_lab_rst.rst_val`
- Gold는 Evaluation Runner만 읽습니다 (Search Logic / Dictionary에 주입 금지)

Gold 구조 예:

```json
{
  "id": "Q001",
  "category": "clinical_natural_language",
  "query": "최근 간수치 검사 결과",
  "gold": {
    "primary_tables": ["public.tb_lab_rst"],
    "acceptable_tables": ["public.tb_lab_mst", "public.tb_lab_ord"],
    "relevant_columns": ["public.tb_lab_rst.rst_val"],
    "relation_tables": ["public.tb_lab_rst", "public.tb_lab_ord"]
  }
}
```

## 5. Experiments

| Name | mode | expand_terms | expand_relations |
|------|------|--------------|------------------|
| keyword_no_expansion | keyword | false | false |
| semantic_no_expansion | semantic | false | false |
| semantic_expansion | semantic | true | false |
| hybrid_no_expansion | hybrid | false | false |
| hybrid_expansion | hybrid | true | false |
| hybrid_expansion_relation | hybrid | true | true (hop=2) |

## 6. Metric 정의

- **Top-1 Primary Accuracy**: 첫 Table Candidate ∈ primary_tables
- **Hit@K (`hit_rate_at_k`)**: Top-K에 Relevant(primary∪acceptable) 1개 이상
- **Mean Recall@K (`mean_recall_at_k`)**: |Top-K ∩ Relevant| / |Relevant|
- **MRR**: 첫 Relevant Table rank의 reciprocal mean
- **Column Hit@K / Column MRR**: relevant_columns가 있는 Query만
- **Relation Recall**: Direct∪Related 에서 gold relation_tables coverage
- COLUMN Document도 부모 Table로 환산 후 Table Candidate Dedup (첫 등장 rank)

## 7. Runner

Official Evaluation은 실제 BGE-M3 Embedding provider만 허용합니다.

- Local Official: `EMBEDDING_PROVIDER=bge_m3`
- Remote Official: `EMBEDDING_PROVIDER=openai_compatible`
- `fake`는 Official에서 차단됩니다 (`--allow-fake`는 unit/dev only)

```bash
# Local Official (sentence-transformers BGE-M3)
docker compose exec \
  -e EMBEDDING_PROVIDER=bge_m3 \
  -e EMBEDDING_MODEL_PATH=/models/local/bge-m3 \
  -e HF_HUB_OFFLINE=1 \
  -e PYTHONPATH=/app \
  backend python -m app.evaluation.runner \
    --gold /app/evaluation/gold_schema_queries.json \
    --output /app/evaluation/results/run_manual

# Remote Official (ALZI OpenAI-compatible BGE-M3 API)
# production container가 이미 openai_compatible으로 구성되어 있으면
# provider override 없이 그대로 실행하면 됩니다.
docker compose exec \
  -e PYTHONPATH=/app \
  backend python -m app.evaluation.runner \
    --gold /app/evaluation/gold_schema_queries.json \
    --output /app/evaluation/results/run_manual_remote
```

본 평가 전 Warm-up Query 1회를 수행하며, Warm-up latency는 통계에서 제외합니다.

## 8. Output 파일

`backend/evaluation/results/<timestamp>/`

- `summary.json` / `summary.csv` / `summary.txt`
- `query_results.jsonl` / `query_results.csv`
- `failures.csv`
- `category_summary.csv`
- `run_metadata.json` (model_key, gold hash, git SHA, timings settings 등)

## 9. Evaluation Viewer

Streamlit `Evaluation Results` 탭에서 저장된 Run을 조회합니다.

- Experiment Comparison / Hit@5·MRR·Latency chart
- Category metrics
- Failure list
- Query detail (Gold / Top / Expansion / Timing)

## 10. 평가 누수 방지 / Search Freeze

- Gold Table/Column을 Terminology·Search Document에 넣지 않음
- Query별 Hardcoding / Ranking Weight 튜닝 금지
- Evaluation은 `SchemaSearchService.search()`를 그대로 호출
- 결과 순서 변조 금지

## 11. 실행 / 테스트

```bash
cp .env.example .env
docker compose up --build

docker compose exec -e EMBEDDING_PROVIDER=fake -e ALLOW_FAKE_SEMANTIC_SEARCH=true \
  -e CATALOG_DB_HOST=catalog-db -e MEDICAL_DB_HOST=medical-db \
  -e CATALOG_DB_PORT=5432 -e MEDICAL_DB_PORT=5432 \
  backend pytest -q
```

## 12. 이번 Step에서 하지 않은 것

- Search Weight / Dictionary 튜닝
- HNSW / LLM / SQL 생성·실행 / Query Router / RAG
- 실제 DEMIS / 환자 데이터 검색

## 13. Multi-DB Architecture

Catalog DB(`schema_catalog`)는 **분석 메타데이터 저장소**이고, Target DB는 읽기 전용 Schema Inspect 대상입니다.

- Target 등록 → (비밀번호는 요청 시에만 사용, 미저장) → Inspector → `CatalogWriter` upsert → Search Document / Embedding
- 모든 Catalog row는 `source_id`로 Target을 구분합니다. 동일 물리 테이블명이라도 Source 간 혼합되지 않습니다.
- **Evaluation Baseline은 계속 `medical_demo`(PostgreSQL mock)** 입니다. Gold Dataset / Terminology / Official Evaluation 결과 / Search Ranking 공식은 Multi-DB 확장과 분리되어 유지됩니다.

## 14. Supported DBMS + Drivers

| DBMS | Driver | Inspector |
|------|--------|-----------|
| PostgreSQL | `psycopg` (`postgresql+psycopg`) | `PostgreSQLSchemaInspector` |
| MySQL | `PyMySQL` (`mysql+pymysql`) | `MySQLSchemaInspector` |
| MariaDB | `PyMySQL` (`mysql+pymysql`) | `MariaDBSchemaInspector` |
| Oracle | `oracledb` Thin (`oracle+oracledb`) | `OracleSchemaInspector` |

Optional local fixtures:

```bash
docker compose --profile integration-dbs up -d mysql-test mariadb-test
# MySQL  host port 3307 / MariaDB host port 3308
# DB=iso_demo user/password=test (root/root)
```

Init SQL: `database/integration/mysql_init.sql`, `database/integration/mariadb_init.sql`
(`tb_shared_patient`, `tb_shared_order`, composite PK/FK 등).

## 15. Target Registration / Password Non-persistence

- `POST /api/v1/targets` 등으로 Target Profile을 등록합니다.
- `catalog_source`에는 host/port/db/user/options만 저장하고 **password는 저장하지 않습니다**.
- Analyze / probe 시점에만 password를 전달하며, 로그·예외 메시지에서는 마스킹합니다.

## 16. Schema Explorer

Streamlit / API에서 Target(`source_id`)을 선택하면 해당 Source의 Table / Column / FK / Index만 탐색합니다.

- `GET /api/v1/schema/tables?source_id=...`
- 복합 PK / UNIQUE / 복합 FK / Index ordinal이 Catalog에 보존됩니다.

## 17. Target-scoped Search

Search / Keyword / Semantic / Relation Expansion은 `source_id`(또는 source_name)로 범위가 제한됩니다.

- 다른 Target의 동일 테이블명 Document가 결과에 섞이지 않습니다.
- Official Evaluation Runner는 `medical_demo` source로 고정합니다.

## 18. Traefik Production Deployment

로컬 기본 `docker-compose.yml`은 **medical-db를 profile 없이** 유지합니다 (pytest/local 기본 동작 유지).

Production override:

- `docker-compose.prod.yml` — medical-db에 `profiles: ["demo"]` (기본 prod는 demo DB 미기동)
- published port 제거 (`ports: !reset []`)
- frontend만 외부 Traefik network + Host/`APP_HOST` TLS 라벨
- backend는 `demis-net` 내부 전용

```bash
cp .env.production.example .env.production
# APP_HOST / CATALOG_DB_PASSWORD / TRAEFIK_* 설정
# 외부 Traefik 네트워크가 이미 있어야 함 (스크립트가 생성하지 않음)

./scripts/deploy.sh          # deploy (default)
./scripts/deploy.sh status
./scripts/deploy.sh logs
./scripts/deploy.sh down     # volumes 유지 (-v 없음)

# medical_demo 가 필요하면:
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml --profile demo up -d
```

Optional Traefik middleware: **빈 `middlewares=` 라벨은 Traefik 오류를 유발**하므로 prod compose에 기본 포함하지 않습니다.
필요할 때만 non-empty 값으로 라벨을 추가하세요 (`.env.production.example` 주석 참고).

## 19. Oracle Thin Mode

- `python-oracledb` **Thin mode** (Instant Client 불필요)
- Easy Connect: `host:port/?service_name=...`
- System schema(SYS/SYSTEM 등)는 inspect 대상에서 제외

Live smoke (환경 변수 전부 있을 때만 실행):

```bash
ORACLE_TEST_HOST=... ORACLE_TEST_PORT=1521 \
ORACLE_TEST_USER=... ORACLE_TEST_PASSWORD=... \
ORACLE_TEST_SERVICE=... pytest backend/tests/test_oracle_live.py -q
```

## 20. Network / Firewall Requirements

- Backend → Target DB: DBMS 포트만 (PostgreSQL 5432, MySQL/MariaDB 3306, Oracle 1521 등). **스키마 메타데이터 SELECT만** 수행합니다.
- Prod: 브라우저 → Traefik (443) → frontend:8501 → backend:8000 (내부 DNS). backend/catalog DB 포트는 호스트에 publish하지 않습니다.
- Traefik Docker network(`TRAEFIK_NETWORK`, 기본 `traefik`)는 사전 생성되어 있어야 합니다.

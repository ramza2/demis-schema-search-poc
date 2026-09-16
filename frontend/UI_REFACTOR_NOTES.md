# DEMIS Schema Analyzer UI refactor

PR #18 UI scope:

- Rename browser/page title from PoC wording to `DEMIS Schema Analyzer`.
- Compact the system health area into one status line plus a details expander.
- Rename primary navigation to `DB Targets / Catalog Explorer / Schema Search / 검증 결과`.
- Replace the vertically separated Target list/add/action sections with per-Target cards.
- Expose `연결 테스트 / Schema 분석 / 수정 / 고급 작업 / 삭제` directly on each Target card.
- Move Target add/edit/delete flows into dialogs to reduce scrolling.
- Keep schema discovery, temporary credentials, document rebuild, and embedding execution under `고급 작업`.
- Preserve existing backend APIs and search/evaluation behavior.

---
plan_id: P-token-revocation
plan_version: 1
readiness: ready
approved: false
approval: {}

bounds:
  max_active_workers: 4
  attempt_limit: 2
  max_depth: 6
  cost_ceiling: 4.0

requirements:
  - id: R-REVOKE
    description: An operator can revoke a single API token, and it stops authenticating on the next request.
    unit_ids: [IU-MIGRATION, IU-STORE, IU-SCHEMA, IU-ENDPOINT]
  - id: R-AUDIT
    description: Every revocation records who revoked which token and when, and the record survives a restart.
    unit_ids: [IU-MIGRATION, IU-STORE]

acceptance:
  - id: AC-REVOKED-FAILS
    description: A token revoked by POST /tokens/{id}/revoke returns 401 on its next request, not at a later cache expiry.
  - id: AC-DOUBLE-REVOKE
    description: Revoking an already revoked token returns 200 and leaves exactly one audit row.
  - id: AC-AUDIT-SURVIVES
    description: An audit row written before a restart is present and unchanged after it.
  - id: AC-REQUEST-SHAPE
    description: A revoke request missing its reason field is rejected with 422 and a named field error.

managers:
  - id: M-STORAGE
    branch: Schema and persistence. Owns the migration and the token store.
  - id: M-API
    branch: HTTP surface. Owns request schemas and the endpoint.

units:
  - unit_id: IU-MIGRATION
    title: Revocation columns and audit table
    objective: Add revoked_at and revoked_by to api_tokens and create the token_revocations audit table.
    kind: implement
    dependencies: []
    acceptance_ids: [AC-AUDIT-SURVIVES]
    read_scope: [migrations/001_initial.sql, src/store/models.py]
    write_scope: [migrations/002_token_revocation.sql]
    forbidden_scope: [.env, .git/, src/api/]
    procedure:
      - Read 001_initial.sql and record the exact api_tokens column set.
      - Write the up and down migration in one file.
      - Apply, roll back, and apply again against a seeded copy.
    commands:
      red: [make migrate-test]
      green: [make migrate-test]
    expected_artifacts: [migrations/002_token_revocation.sql]
    output_contract:
      - The up migration adds exactly revoked_at and revoked_by to api_tokens and creates token_revocations.
      - Every pre-existing api_tokens row still selects, with revoked_at NULL.
      - The down path leaves the schema byte-identical to 001_initial.sql.
    progress_contract:
      checkpoint_every: single pass, the migration file is written once
      writes_incrementally: false
      command_timeout_seconds: 120
    manager_id: M-STORAGE
    risk: high
    route:
      primary: local
      fallback: local
    attempt_limit: 2
    stop_conditions:
      - A column name collides with an existing one.
      - The seeded copy is unavailable.

  - unit_id: IU-SCHEMA
    title: Revoke request and response schemas
    objective: Define the request and response bodies for the revoke endpoint, with validation.
    kind: implement
    dependencies: []
    acceptance_ids: [AC-REQUEST-SHAPE]
    read_scope: [src/api/schemas.py, src/api/routes.py, tests/test_schemas.py]
    write_scope: [src/api/schemas.py, tests/test_schemas.py]
    forbidden_scope: [.env, .git/, migrations/, src/store/]
    procedure:
      - Read the existing schema module and follow its validation style.
      - Add the revoke request and response models with a required reason field.
      - Write tests covering the missing-field and wrong-type cases.
    commands:
      red: [pytest tests/test_schemas.py]
      green: [pytest tests/test_schemas.py]
    expected_artifacts: [src/api/schemas.py, tests/test_schemas.py]
    output_contract:
      - A revoke request without a reason fails validation with a named field error, not a generic one.
      - tests/test_schemas.py contains at least one test per acceptance id and all pass.
    progress_contract:
      checkpoint_every: each schema, then each test
      writes_incrementally: true
      command_timeout_seconds: 120
    manager_id: M-API
    risk: low
    route:
      primary: local
      fallback: local
    attempt_limit: 2
    stop_conditions:
      - The existing schema module uses a validation library this change cannot extend.

  - unit_id: IU-STORE
    title: Revocation repository and audit write
    objective: Add revoke_token and is_revoked to the token store, writing one audit row per revocation and none on a repeat.
    kind: implement
    dependencies: [IU-MIGRATION]
    acceptance_ids: [AC-DOUBLE-REVOKE, AC-AUDIT-SURVIVES]
    read_scope:
      - src/store/tokens.py
      - src/store/models.py
      - migrations/002_token_revocation.sql
      - tests/test_token_store.py
    write_scope: [src/store/tokens.py, tests/test_token_store.py]
    forbidden_scope: [.env, .git/, src/api/, migrations/001_initial.sql]
    procedure:
      - Read the applied migration for the exact column and table names.
      - Implement revoke_token as an upsert so a retry cannot duplicate the audit row.
      - Implement is_revoked as a committed read, not a cache populated at process start.
    commands:
      red: [pytest tests/test_token_store.py]
      green: [pytest tests/test_token_store.py]
    expected_artifacts: [src/store/tokens.py, tests/test_token_store.py]
    output_contract:
      - revoke_token and is_revoked are importable from src/store/tokens.py.
      - A second revoke_token call on the same token leaves exactly one audit row.
      - tests/test_token_store.py contains at least one test per acceptance id and all pass.
    progress_contract:
      checkpoint_every: each function, then each test
      writes_incrementally: true
      command_timeout_seconds: 180
    manager_id: M-STORAGE
    risk: medium
    route:
      primary: local
      fallback: local
    attempt_limit: 2
    stop_conditions:
      - The migration did not create the columns this unit was told to use.

  - unit_id: IU-ENDPOINT
    title: Revoke endpoint
    objective: Expose POST /tokens/{id}/revoke, returning 200 on both first and repeat revocation.
    kind: implement
    dependencies: [IU-STORE, IU-SCHEMA]
    acceptance_ids: [AC-REVOKED-FAILS, AC-DOUBLE-REVOKE]
    read_scope:
      - src/api/routes.py
      - src/api/schemas.py
      - src/store/tokens.py
      - tests/test_api_revoke.py
    write_scope: [src/api/routes.py, tests/test_api_revoke.py]
    forbidden_scope: [.env, .git/, migrations/, src/store/models.py]
    procedure:
      - Read the store interface and the request schema; do not reimplement either.
      - Add the route, delegating idempotency and auditing to the store.
      - Write an end-to-end test that authenticates with a token, revokes it, and retries.
    commands:
      red: [pytest tests/test_api_revoke.py]
      green: [pytest tests/test_api_revoke.py, pytest tests/]
    expected_artifacts: [src/api/routes.py, tests/test_api_revoke.py]
    output_contract:
      - A revoked token returns 401 on its very next authenticated request.
      - A second revoke of the same token returns 200, not 404 or 409.
      - The full suite passes, not only this unit's file.
    progress_contract:
      checkpoint_every: the route, then each test
      writes_incrementally: true
      command_timeout_seconds: 300
    manager_id: M-API
    risk: medium
    route:
      primary: local
      fallback: local
    attempt_limit: 2
    stop_conditions:
      - The store interface does not expose what the route needs.
      - Authentication middleware caches token state in a way this change cannot reach.
---

# Token revocation

## 1. Goal and Requirements

Operators can currently issue API tokens but not withdraw one. A leaked token is
live until it expires. This adds immediate revocation with an audit trail.

In scope: revocation of a single token, its audit record, and the endpoint.
Out of scope: bulk revocation, token rotation, and any change to issuance.

Requirements are `R-REVOKE` and `R-AUDIT` in the frontmatter, with acceptance
`AC-REVOKED-FAILS`, `AC-DOUBLE-REVOKE`, `AC-AUDIT-SURVIVES`, and
`AC-REQUEST-SHAPE`.

## 2. Grounding

- `migrations/001_initial.sql:14` creates `api_tokens` with no revocation column.
- `src/store/tokens.py:31` reads token state through `load_token`, which returns
  a row and does not consult any cache.
- `src/api/routes.py:88` is where token routes are registered.
- Baseline: `pytest tests/` passes, 41 tests, before this change. New failures
  are therefore distinguishable from old ones.

## 3. Decisions and Evidence

- **Revocation is a column, not a delete.** The audit requirement needs the row
  to survive, and `R-AUDIT` names a restart explicitly.
- **Idempotency lives in the store, not the route.** Two entry points would
  otherwise each need it, and the double-revoke acceptance is a data property.
- **`is_revoked` reads committed state.** The auth middleware at
  `src/api/middleware.py:22` reads per request, so no cache invalidation is
  needed; this was checked rather than assumed.

## 4. Units

Four units in the frontmatter. `IU-MIGRATION` and `IU-SCHEMA` have no
dependencies and run together. `IU-STORE` waits for the migration; `IU-ENDPOINT`
waits for both the store and the schemas. No two units that can run at the same
time write the same file.

## 5. Verification and Done

Done when `pytest tests/` passes with the four new acceptance tests included, the
migration applies and rolls back cleanly, and every unit's output contract holds
against its artifact rather than against its existence.

## 6. Risks and Recovery

- **The migration is the only high-risk unit.** Its down path is exercised in the
  same command that applies it, so a bad migration is caught before `IU-STORE`
  starts.
- If `IU-MIGRATION` reaches `human_required`, `IU-STORE` and `IU-ENDPOINT` are
  blocked with it. `IU-SCHEMA` is independent and keeps running.

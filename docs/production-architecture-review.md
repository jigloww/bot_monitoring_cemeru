# Production Architecture Review

**Repository:** `bot_monitoring_cemeru`  
**Review type:** Read-only production architecture review  
**Release target:** Version 1.0  
**Recommendation:** **NO-GO for v1.0**

## Executive verdict

| Area | Score | Assessment |
|---|---:|---|
| Overall architecture | **5.0/10** | Domain structure and research foundations exist, but contracts and boundaries are incomplete |
| Production readiness | **2.5/10** | Security, reproducibility, CI, state management, and deployment blockers remain |

The repository has a useful research foundation: domain directories are clear,
experiment artifacts are generally write-once, and the architecture blueprint
describes a credible future design. It is not yet a reproducible production
release because generated runtime state, source history, testing, and deployment
contracts are not aligned.

## Repository structure

The repository currently combines three products:

```text
bot/
  Telegram monitoring application

stealth/
  Browser-side runtime and domain modules

tools/
  Fingerprint collectors, comparator, scorer, and patch generator

experiments/
  Research runners, diagnostics, and dashboard

reports/
  Generated runtime and research artifacts
```

The structure is understandable, but production monitoring, browser research,
Cloudflare diagnostics, and generated artifacts are still part of one release
unit. The working tree is also not release-clean: it contains one modified
tracked file and numerous untracked modules, experiments, and report trees.

## Dependency graph

```text
semeru_quota_bot.py
 ├─ bot.monitor
 │   └─ bot.clients.playwright_client
 │       ├─ Playwright
 │       ├─ requests
 │       └─ playwright-stealth
 ├─ bot.telegram
 │   └─ bot.handlers
 │       └─ bot.messages
 │           └─ bot.monitor
 └─ bot.state / scheduler / config

tools.fingerprint_dump
 └─ tools.compare_fingerprint
     ├─ tools.browser_score
     ├─ tools.patch_generator
     └─ tools.patch_validator

stealth.apply
 ├─ stealth.loader
 ├─ stealth.registry
 ├─ stealth/runtime/*
 ├─ stealth/modules/*
 └─ stealth/generated/*

experiments/*
 ├─ tools.compare_fingerprint
 ├─ tools.browser_score
 ├─ tools.patch_validator
 ├─ stealth.apply
 └─ duplicated per-experiment orchestration
```

There is a conceptual Telegram cycle: `telegram -> handlers -> messages ->
monitor`, while `handlers` imports Telegram sending functions. It currently
works through deferred imports, but increases coupling and makes isolated tests
harder.

## Strengths

- Clear high-level separation between `bot/`, `stealth/`, `tools/`, and `experiments/`.
- A reusable experiment allocator with write-once artifact helpers.
- Shared browser launch and filesystem helpers already exist.
- Pure message-building functions are relatively easy to test.
- `WebsiteStatus` and `WebsiteError` provide a useful basis for typed failure handling.
- Chrome/Chromium fallback exists in the browser client.
- The stealth architecture document already defines module ownership, schemas,
  dependency resolution, and rollback concepts.
- Diagnostic experiments correctly distinguish environment/network failures from
  fingerprint similarity.

## Major findings

### 1. Module selection is not honored

`apply_stealth(..., modules=...)` accepts a module list but does not use it:

[stealth/apply.py:58](../stealth/apply.py#L58)

The context-level apply function also accepts unused keyword arguments. This
means callers cannot safely select or disable modules, which is a critical
feature-flag and rollback failure.

### 2. Registry state does not describe actual runtime state

The registry records only a name, path, description, enabled flag, and status.
It has no dependency graph, ordering constraints, ownership, conflicts, schema
version, hash validation, or structured load report.

`performance` is marked as a placeholder even though its JavaScript file exists:

[stealth/registry.py:91](../stealth/registry.py#L91)

Missing files can also be silently omitted while remaining marked active.

### 3. Generated patch artifacts are inconsistent

The active generated patch files are not synchronized with historical reports:

- `stealth/generated/patches_init.js` is effectively empty.
- `stealth/generated/patches.json` contains `{}` instead of the expected manifest.
- `stealth/generated/patches.py` is a no-op.
- `reports/patches/patches.py` fails Python compilation.

The failure occurs at:

[reports/patches/patches.py:25](../reports/patches/patches.py#L25)

This makes the current patch pipeline non-reproducible.

### 4. Production bot and local stealth framework are separate runtimes

The production browser client uses `playwright-stealth` directly:

[bot/clients/playwright_client.py:497](../bot/clients/playwright_client.py#L497)

It does not use `stealth.apply_stealth`. Therefore module experiment results do
not automatically represent production bot behavior.

### 5. Browser identity is hardcoded

The client defines a static Chrome 126 user agent:

[bot/clients/playwright_client.py:41](../bot/clients/playwright_client.py#L41)

The current browser environment is newer. Static UA, locale, timezone, viewport,
platform, and request headers can diverge from the actual browser binary and
deployment host.

### 6. State persistence is not production-safe

[bot/state.py:33](../bot/state.py#L33) writes JSON directly. There is no atomic
replace, file lock, schema version, checksum, backup, or multi-instance guard.
Corrupt state is silently replaced with defaults, which can cause duplicate
notifications or lost monitoring history.

### 7. Broad exception handling hides root causes

Many layers catch `Exception` and convert failures into defaults, missing values,
or generic `UNKNOWN` results. Telegram failures can be confused with website
failures, browser errors can become missing fingerprint properties, and parser
errors can be hidden as empty data.

### 8. Experiment code is heavily duplicated

The Navigator, Window, Screen, Chrome, Permissions, Fonts, Speech, Performance,
and WebGL evaluators repeat browser collection, category scoring, mode handling,
report rendering, CLI parsing, and conclusions. A common generic scenario
runner should replace this copy-and-modify pattern.

### 9. Comparator and scorer are tightly coupled

`browser_score.py`, `patch_generator.py`, `patch_validator.py`, and experiment
metrics import comparator internals directly. The comparator currently owns
flattening, equality, knowledge base, categories, recommendations, rendering,
and CLI behavior.

The scorer is useful for relative experiments but should not be a production
acceptance gate because it uses category averages and still includes volatile
fields. The `cf_risk_score` name also describes a similarity score rather than
an observed Cloudflare outcome.

### 10. Dashboard is stale and schema-dependent

The committed dashboard reflects earlier experiments while later experiment
directories exist. Its module list is limited to the nine stealth domains, so
network, environment, and Cloudflare diagnostics are not represented as first-
class run types.

[reports/dashboard/dashboard.json](../reports/dashboard/dashboard.json)

### 11. Sensitive diagnostic artifacts are retained

Reports include challenge payloads, network logs, HTML snapshots, screenshots,
headers, and cookie-related observations. These should be redacted and stored in
an artifact store rather than shipped as source-controlled production data.

The workspace also contains a Telegram credential in `.env`. It should be
rotated immediately and managed through a secret manager.

### 12. Deployment packaging is incomplete

There is no Dockerfile, CI workflow, systemd unit, release manifest, or formal
health check. Deployment scripts contain host-specific paths:

[scripts/notify_failure.sh:8](../scripts/notify_failure.sh#L8)

The environment example uses `CHECK_INTERVAL`, while code reads
`CHECK_INTERVAL_SECONDS`:

[config/.env.example:6](../config/.env.example#L6)

Fresh deployments can therefore silently use defaults.

## High-risk components

| Component | Risk | Severity |
|---|---|---|
| `.env` and raw reports | Credential/session/privacy exposure | Critical |
| `stealth/generated/*` and `reports/patches/*` | Runtime/report drift and invalid generated code | Critical |
| `stealth/apply.py` | Module selection and rollback ineffective | Critical |
| `bot/state.py` | State loss, corruption, duplicate alerts | High |
| `bot/clients/playwright_client.py` | UA mismatch, profile/cookie reuse, browser lifecycle | High |
| Browser launch flags | Unconditional `--no-sandbox` | High |
| Telegram polling | In-memory offset, rate limits, duplicate processing | High |
| Experiment suite | Duplicated logic and schema drift | High |
| `reports/` | Unredacted diagnostic data and uncontrolled retention | High |
| Deployment scripts | Host-specific paths and missing release automation | Medium |

## Recommended repository restructuring

```text
pyproject.toml
src/
  semeru_bot/
    application/
    domain/
    adapters/browser/
    adapters/telegram/
    persistence/
    observability/
    config.py
  fingerprint_core/
    models.py
    schema.py
    normalize.py
    compare.py
    scoring.py
    knowledge.py
  stealth_framework/
    api.py
    registry.py
    loader.py
    bundle.py
    schemas/
    runtime/
    modules/
  experiment_runner/
    models.py
    scenarios/
    collectors/
    reports/
tests/
  unit/
  integration/
  browser/
  fixtures/
deploy/
  systemd/
  docker/
  staging/
  production/
```

`tools/` should become compatibility CLI wrappers around these packages rather
than the primary internal dependency layer.

## Suggested package boundaries

### `semeru_bot`

Own quota domain logic, parser, monitoring service, Telegram adapter, state
store, scheduler, configuration, logging, and health checks. The monitor should
depend on an abstract quota source rather than directly on Playwright.

### `fingerprint_core`

Own schema, normalization, stable/volatile policy, comparison, scoring, and
consistency validation. No consumer should import comparator constants directly.

### `stealth_framework`

Own manifests, dependency resolution, module ownership, profiles, bundle
assembly, feature flags, load reports, and immutable patch sets.

### `experiment_runner`

Own browser matrices, immutable run allocation, collectors, schemas, and
artifact retention. Each experiment should be configuration, not a new copy of
the orchestration engine.

## Technical debt ranking

### P0 — release blockers

1. Rotate credentials and remove sensitive artifacts from release history.
2. Reconcile active generated files with committed source.
3. Fix invalid generated Python output.
4. Implement actual module selection and registry resolution.
5. Add atomic, versioned state persistence.
6. Pin dependencies and browser revisions.
7. Establish CI with compile, unit, JavaScript, schema, and browser smoke tests.
8. Decide whether production uses local stealth modules or `playwright-stealth`.
9. Replace hardcoded browser identity with validated profiles.
10. Define a secure launch policy instead of unconditional `--no-sandbox`.

### P1 — reliability and maintainability

1. Add typed error taxonomy and retry/backoff policy.
2. Add graceful shutdown and guaranteed browser cleanup.
3. Persist Telegram polling offset.
4. Add rate limiting and idempotent notification delivery.
5. Add state locking and multi-instance protection.
6. Consolidate evaluation scripts into one generic scenario runner.
7. Add versioned JSON schemas for fingerprints and reports.
8. Redact cookies, headers, challenge payloads, and HTML by default.
9. Make the dashboard consume a common run manifest.
10. Add module ownership and cross-domain invariant validation.

### P2 — cleanup

1. Fix README, `.env.example`, and changelog drift.
2. Remove unused registry hooks and placeholder runtime files.
3. Add type checking, formatting, linting, and import-cycle checks.
4. Add module documentation and authoring templates.
5. Separate research terminology from production terminology.
6. Add report retention and privacy policies.

## Feature flag strategy

Recommended flags:

```text
STEALTH_ENGINE=off|legacy|v1
STEALTH_MODULES=navigator,window,screen
STEALTH_PATCH_SET=<immutable-id>
STEALTH_PROFILE=<profile-id>
STEALTH_MODE=strict|warn|dry-run|inspect
STEALTH_EXPERIMENTAL=false
```

Production should default to native browser behavior or explicitly approved
stable modules. High-risk modules should be disabled by default. Every enabled
module must declare ownership, dependencies, version, conflicts, and a patch-set
hash.

## Rollback strategy

Use immutable application releases and immutable stealth patch sets with an
active pointer. Rollback should switch the pointer atomically without
regeneration. Add per-module kill switches, browser-profile backup/reset, and
automatic rollback for browser launch errors, notification failures, stable
regressions, challenge spikes, or state corruption.

The current repository has experiment immutability but no runtime patch-set
rollback mechanism.

## Public API recommendations

Recommended stable APIs:

- `stealth.apply_stealth`
- `stealth.apply_generated` as a compatibility API
- `stealth.apply_modules` after selection semantics are fixed
- `experiments.Experiment`
- `experiments.ExperimentConfig`
- `experiments.ExperimentMetrics`
- `bot.website_status.WebsiteStatus`
- `bot.website_status.WebsiteError`
- Pure parser functions from `bot.monitor`
- Versioned fingerprint comparison and scoring APIs

These should remain internal implementation details:

- `tools.compare_fingerprint.KB`
- `tools.browser_score.CATEGORY_WEIGHT`
- Registry internals
- Generated JavaScript files
- Experiment-specific helper functions
- Unversioned raw report schemas

## Archive recommendations

Move outside the production source tree:

- `test.html`
- `test.png`
- Raw `reports/` snapshots, HAR files, screenshots, and challenge payloads
- Old experiment directories after extracting curated fixtures
- Invalid `reports/patches/patches.py` after regeneration
- Placeholder runtime files `stealth/runtime/hooks.js` and `proxy.js`
- Host-specific `scripts/notify_failure.sh` until corrected
- One-off diagnostic scripts after generic consolidation
- Individual module evaluation scripts after generic scenario migration

Keep only small, redacted golden fixtures and schema examples in the repository.

## Migration roadmap toward v1.0

### Phase 0 — Release freeze

- Rotate credentials.
- Clean and classify the Git working tree.
- Remove secrets and sensitive reports.
- Define supported OS, Python, Playwright, and browser versions.
- Freeze current behavior as regression fixtures.

### Phase 1 — Build foundation

- Add `pyproject.toml`.
- Pin dependencies and browser revisions.
- Add CI and formal tests.
- Add schema validation and release metadata.

### Phase 2 — Harden monitoring bot

- Extract browser, HTTP, Telegram, and persistence adapters.
- Add atomic state storage, retries, backoff, idempotency, and graceful shutdown.
- Add health/readiness checks.
- Remove hardcoded browser identity.

### Phase 3 — Extract fingerprint core

- Split comparator, normalization, knowledge, scoring, and rendering.
- Preserve existing CLIs as compatibility wrappers.
- Add stable/volatile policy and consistency metrics.

### Phase 4 — Implement stealth v1 runtime

- Manifest-based registry.
- Dependency graph and cycle detection.
- Module ownership and conflict validation.
- Versioned profiles and patch sets.
- Strict/warn/dry-run modes.
- Deterministic bundle and load report.

### Phase 5 — Consolidate experiments

- One generic experiment runner.
- Common run manifest and report schema.
- Dashboard based on manifests instead of filename heuristics.

### Phase 6 — Deployment hardening

- systemd or container artifact.
- Secret manager integration.
- Canary rollout.
- Metrics, alerting, profile backup, and tested rollback.

### Phase 7 — v1.0 gate

Release only when CI is reproducible, no P0 findings remain, generated
artifacts compile, module selection is deterministic, rollback is tested, and
sensitive artifacts are excluded.

## Validation observations

- Python compileall for `bot`, `tools`, `experiments`, and `stealth`: passed.
- Stealth JavaScript `node --check`: passed.
- Generated JavaScript syntax: passed.
- `pytest --collect-only`: unavailable because `pytest` is not installed and no
  formal `tests/` package exists.
- Generated report Python: failed at `reports/patches/patches.py:25`.

## Final recommendation

The repository is a promising research platform, but not yet a production-grade
v1.0 system. The first release should focus on security, reproducibility, module
selection, state durability, browser lifecycle, CI, and strict separation between
the monitoring bot and research tooling.

The architecture direction in
[`docs/stealth-framework-v1-architecture.md`](stealth-framework-v1-architecture.md)
is suitable as a migration blueprint once the P0 issues are resolved.

# Production Integration Blueprint — Local Stealth Framework

**Phase:** 4 — Production Engineering  
**Scope:** Replace `playwright-stealth` with the local Stealth Framework  
**Status:** Design-only specification  
**Implementation:** Not performed in this phase

## 1. Current state

The production browser client currently constructs `playwright-stealth`
directly:

[bot/clients/playwright_client.py:497](../bot/clients/playwright_client.py#L497)

The local framework exposes:

- `stealth.apply_generated()`
- `stealth.apply_modules()`
- `stealth.apply_stealth()`
- `stealth.apply_stealth_context()`

Important integration gaps remain:

- `apply_stealth(..., modules=...)` does not currently honor module selection.
- `apply_stealth_context(..., **kwargs)` accepts options that are not used.
- Registry resolution has no dependency graph, conflict detection, ownership, or version validation.
- `stealth/generated/patches_init.js` is still a legacy runtime path.
- Production and experiment browser launch configuration is duplicated.
- Persistent profile state is global through `data/browser_profile`.
- Browser-to-HTTP session state is held in a process-global `_session`.

## 2. Design principles

1. Engine selection happens before browser context creation.
2. One context uses one stealth engine only.
3. Legacy and local engines must never be applied to the same page.
4. Module order is deterministic.
5. Patch sets are immutable and hash-addressed.
6. Browser profiles are isolated by engine identity.
7. Local stealth can be disabled without changing `fetch_html()` behavior.
8. Fallback is explicit and observable.
9. Shadow mode cannot alter alerts, quota state, cookies, or primary sessions.
10. Engine, module, profile, and patch-set decisions are logged without secrets.

## 3. Feature flag architecture

### Engine modes

```text
off
legacy
local
shadow
```

| Mode | Primary browser | Local framework | Use case |
|---|---|---|---|
| `off` | Native browser | Disabled | Emergency fallback |
| `legacy` | `playwright-stealth` | Disabled | Existing production behavior |
| `local` | Local Stealth Framework | Enabled | Target production mode |
| `shadow` | Legacy primary | Local secondary context | Migration validation |

### Recommended configuration

```text
STEALTH_ENGINE=legacy
STEALTH_MODULES=navigator,window,screen,chrome
STEALTH_PATCH_SET=active
STEALTH_PROFILE=production-default
STEALTH_MODE=strict
STEALTH_SHADOW_ENABLED=false
STEALTH_SHADOW_SAMPLE_RATE=0.0
STEALTH_EXPERIMENTAL=false
```

### Configuration precedence

```text
Built-in defaults
    ↓
Configuration file
    ↓
Environment variables
    ↓
Explicit process/CLI options
```

Configuration must be parsed once at startup and converted into an immutable,
typed object.

Startup must reject unknown engines, unknown modules, duplicate modules,
invalid patch sets, missing required modules, incompatible browser channels, and
profiles shared by different engine identities.

### Operational logging

Every browser context should record:

```text
engine
modules
patch_set_id
patch_set_hash
profile_id
browser_channel
browser_version
headless
resolution_status
```

Cookies, tokens, profile contents, and other secrets must not be logged.

## 4. Stealth Engine abstraction

The monitoring bot should depend on an engine abstraction rather than on
`playwright-stealth` or local JavaScript modules directly.

### Conceptual interface

```text
StealthEngine
 ├─ resolve()
 ├─ validate()
 ├─ prepare_context()
 ├─ install_context()
 ├─ describe()
 ├─ health()
 └─ close()
```

### `LegacyStealthEngine`

Wraps the current `playwright-stealth` behavior and preserves existing
navigator overrides, fallback behavior, and the browser client's public
contract.

### `LocalStealthEngine`

Uses the local registry, patch-set resolver, runtime bundle builder, and
`context.add_init_script()`.

Responsibilities:

- Resolve enabled modules.
- Load runtime scripts.
- Load only requested modules.
- Inject validated profile data.
- Assemble one deterministic init script.
- Install it before page navigation.

### `DisabledStealthEngine`

Does not inject JavaScript. It is used for emergency rollback, browser baseline
testing, and environment diagnosis.

### `ShadowStealthEngine`

Owns two isolated contexts:

```text
Primary context  → LegacyStealthEngine
Shadow context   → LocalStealthEngine
```

The contexts must not share cookies, profiles, storage state, session objects,
alerts, or quota state.

## 5. Module loading lifecycle

```text
requested
  ↓
configuration validated
  ↓
registry resolved
  ↓
patch set resolved
  ↓
profile validated
  ↓
runtime capabilities checked
  ↓
bundle assembled
  ↓
bundle hash calculated
  ↓
context created
  ↓
init script installed
  ↓
page created
  ↓
navigation begins
  ↓
runtime/module health collected
  ↓
context closed
```

Before `page.goto()`, module dependencies, order, patch-set data, profile data,
syntax, and bundle assembly must all be validated.

### Failure policy

- **Strict:** required module failure stops startup.
- **Warn:** optional modules may be skipped with an explicit load report.
- **Emergency:** failure switches to legacy or native mode according to the
  active rollback policy.

The engine must guarantee one bundle per context, one installation marker, and
no repeated `add_init_script()` for the same bundle.

## 6. Patch-set lifecycle

The current `stealth/generated/patches_init.js` should remain a compatibility
artifact, not the long-term production contract.

### Target layout

```text
stealth/generated/sets/
  ps-<id>/
    manifest.json
    profile.json
    navigator.json
    window.json
    screen.json
    chrome.json
    permissions.json
    fonts.json
    speech.json
    performance.json
    webgl.json
```

### Manifest requirements

Each patch set should contain:

```text
patch_set_id
schema_version
created_at
source_commit
baseline_id
browser_family
browser_version_range
profile_id
module list
module ownership
source hashes
data hashes
validation status
promotion status
```

### Patch-set states

```text
draft
validated
shadow
canary
active
retired
revoked
```

Patch-set promotion requires schema validation, hash verification, ownership
validation, runtime syntax validation, strict browser smoke tests, shadow
observation, and successful rollback testing.

Promotion must never overwrite an existing patch set.

### Active pointer

Use an immutable pointer such as:

```text
stealth/generated/active.json
```

The pointer identifies the active patch-set ID and hash. Rollback changes the
pointer, not patch-set contents.

The future generator should produce data and metadata only. Runtime
implementation logic belongs to domain modules.

## 7. Browser profile lifecycle

The current shared profile path:

```text
data/browser_profile
```

is insufficient for dual-engine migration.

### Profile identity

```text
profile_id
browser_channel
browser_major_version
engine
target_group
locale
timezone
viewport_class
created_at
last_known_good
```

### Target profile layout

```text
data/browser_profiles/
  production/
    legacy/
      chrome/
    local/
      chrome/
    chromium/
  shadow/
    local/
```

Legacy and local engines must never share a persistent profile. Shadow contexts
should normally use temporary profiles.

Profile management must include locks, metadata, backup, compatibility checks,
quarantine, and reset procedures. Browser major-version changes must trigger a
profile compatibility check.

### Profile state transitions

```text
uninitialized → created → validated → active → degraded → quarantined → retired
```

## 8. Rollback strategy

Rollback should operate at four levels:

1. **Module rollback:** disable one module.
2. **Patch-set rollback:** change the active patch-set pointer.
3. **Engine rollback:** change local mode back to legacy.
4. **Native rollback:** disable all stealth injection.

Automatic rollback signals should include browser launch failures, page
initialization failures, increased request failures, timeout spikes, profile
corruption, session extraction failures, and repeated monitoring failures.

Rollback must emit one operational notification and avoid alert floods.

## 9. Shadow mode architecture

```text
Monitoring cycle
    │
    ├─ Primary context
    │    └─ LegacyStealthEngine
    │         └─ Existing quota/session path
    │
    └─ Shadow context
         └─ LocalStealthEngine
              └─ Diagnostic-only observation
```

Shadow execution must not send Telegram messages, update quota state, transfer
cookies, reuse the primary profile, submit forms, or influence monitoring
results.

Collect only operational signals:

- Context and page launch success.
- Navigation status and final URL.
- Redirects and request failures.
- Console and page errors.
- Browser crashes.
- Navigation timing.
- Module load report.
- Profile initialization result.
- Cookie count without cookie values.

Initial sampling should be approximately 1–5%, with one shadow run per interval,
a shorter timeout than the primary path, and an allowlist of safe targets.

## 10. Legacy compatibility

The following guarantees should remain during migration:

- `fetch_html(url, data=None)` keeps its current contract.
- `apply_generated()` remains available.
- Existing experiment runners remain runnable.
- Existing generated artifacts remain readable.
- `playwright-stealth` remains installed during the compatibility period.
- Legacy mode remains the default until canary promotion.
- Existing profiles are not migrated in place.

Both engines must never run on the same page or context.

## 11. Target dependency graph

```text
bot.config
   │
   ▼
StealthConfig
   │
   ▼
StealthEngineFactory
   ├─ LegacyStealthEngine
   ├─ LocalStealthEngine
   ├─ DisabledStealthEngine
   └─ ShadowStealthEngine
          │
          ├─ RegistryResolver
          ├─ PatchSetResolver
          ├─ ProfileStore
          ├─ BundleBuilder
          └─ EngineHealthReporter
                          │
                          ▼
                BrowserContext
                          │
                          ▼
                Playwright Page
                          │
                          ▼
                bot.clients.playwright_client
                          │
                          ▼
                bot.monitor
                          │
                          ▼
                quota state and notifications
```

The dependency direction is:

```text
monitoring application → browser client → engine abstraction
```

The monitoring application must not import stealth module implementations.

## 12. Integration sequence

### Step 1 — Freeze legacy behavior

Record launch options, profile behavior, session extraction, challenge
observations, and failure classifications.

Acceptance criterion: legacy mode remains operationally equivalent.

### Step 2 — Add engine abstraction

Introduce the interface and legacy adapter without changing the default mode.

### Step 3 — Add local resolver path

Add registry resolution, profile validation, patch-set resolution, and bundle
metadata. Local mode remains dry-run only.

### Step 4 — Move installation to context lifecycle

Install local scripts with `context.add_init_script()` before page creation and
navigation.

### Step 5 — Add isolated profiles

Create separate legacy, local, and shadow profile identities.

### Step 6 — Enable shadow mode

Run local mode in an isolated secondary context while legacy remains primary.

### Step 7 — Canary local mode

Activate local mode for a controlled target or deployment instance. Validate
launch reliability, request failures, timeouts, profile health, and alert
behavior.

### Step 8 — Promote local mode

Switch the production default only after the canary passes. Keep legacy mode for
at least two release cycles.

### Step 9 — Retire legacy dependency

Remove direct client imports only after local mode is stable and rollback remains
available.

## 13. Migration plan

### Milestone 1 — Integration foundation

Scope:

- Typed feature flags.
- Engine abstraction.
- Legacy adapter.
- Local adapter.
- Registry resolution seam.
- Context-level installation seam.
- Structured engine metadata.
- No default behavior change.

Out of scope:

- New stealth modules.
- Fingerprint tuning.
- New experiments.
- Dashboard changes.
- Comparator changes.
- Generator redesign.
- Production activation.

### Milestone 2 — Local dry-run

Validate module manifests, patch-set manifests, profile identity, and resolution
reports without production browser activation.

### Milestone 3 — Shadow

Add isolated shadow contexts, profile isolation, health metrics, and resource
limits.

### Milestone 4 — Canary

Activate local mode in a controlled deployment with automatic rollback.

### Milestone 5 — Local default

Promote local mode while retaining legacy and native emergency paths.

### Milestone 6 — Legacy retirement

Remove direct dependency, retain compatibility wrappers, and archive legacy
runtime artifacts.

## 14. Risk analysis

| Risk | Impact | Mitigation |
|---|---|---|
| Both engines applied to one page | Conflicting descriptors and unpredictable behavior | Engine ownership enforced at context level |
| Module order changes | Runtime inconsistency | Manifest dependency graph and deterministic ordering |
| Generated patch overrides local module | Local behavior silently replaced | Local bundle excludes legacy patches unless explicitly compatible |
| Profile contamination | Cookies and identity cross engines | Separate profile IDs, locks, and directories |
| Browser version mismatch | Invalid UA/profile assumptions | Version-pinned profiles and preflight validation |
| Local engine load failure | Monitoring outage | Legacy/native fallback policy |
| Shadow doubles traffic | Rate limiting or target load | Sampling, allowlists, and timeouts |
| Shadow affects alerts | Incorrect operational behavior | Shadow has no state or notification access |
| Wrong cookie bridge | HTTP quota failure | Session bridge scoped to primary context |
| Persistent profile lock | Startup failure | Lock management and quarantine |
| Module intrinsic side effects | Global browser behavior changes | Ownership and health validation |
| Registry false availability | Misleading activation | Resolve availability at startup |
| Diagnostic secret leakage | Security incident | Redaction, retention, and external storage |
| Incomplete rollback | Continued bad runtime | Engine, patch-set, module, and profile rollback |
| Network failure mistaken for engine failure | Incorrect promotion | Separate environment readiness from engine health |

## 15. Required code changes

### Configuration

Modify `bot/config.py` to add typed engine, module, patch-set, profile, strict
mode, and shadow configuration.

### Browser client

Modify `bot/clients/playwright_client.py` to:

- remove direct engine construction from the main flow
- inject `StealthEngine`
- install at context lifecycle
- preserve `fetch_html()`
- retain primary session/cookie behavior
- report engine health
- guarantee context cleanup

### Stealth application layer

Modify:

- `stealth/apply.py`
- `stealth/loader.py`
- `stealth/registry.py`
- `stealth/__init__.py`

Required capabilities:

- real module selection
- deterministic resolution
- strict/warn modes
- patch-set resolution
- bundle metadata and hashes
- duplicate-install protection
- separation of legacy and local bundles

### Future framework files

These are proposed implementation targets, not created by this blueprint:

```text
stealth/engine.py
stealth/config.py
stealth/registry_resolver.py
stealth/patch_sets.py
stealth/profiles.py
stealth/bundle.py
stealth/health.py
stealth/schemas/
bot/clients/stealth_engine.py
tests/stealth/
tests/integration/
```

### Dependency packaging

Modify `requirements.txt` only during legacy retirement:

- pin supported versions
- document browser revisions
- retain `playwright-stealth` during migration
- remove it only after legacy retirement

## 16. Files that must remain untouched during Milestone 1

- `stealth/modules/*`
- `stealth/runtime/*`
- `tools/*`
- `experiments/*`
- `reports/*`
- `browser_score.py`
- `compare_fingerprint.py`
- `patch_generator.py`
- `patch_validator.py`
- `dashboard.py`
- `bot/monitor.py`
- `bot/telegram.py`
- `bot/messages.py`
- `bot/scheduler.py`
- `bot/website_status.py`
- `semeru_quota_bot.py`

Existing modules should be integrated as-is first. Module behavior changes,
fingerprint tuning, and new experiments belong to later milestones.

## 17. Milestone 1 acceptance criteria

Milestone 1 is complete when:

- `STEALTH_ENGINE=legacy` preserves current behavior.
- `STEALTH_ENGINE=off` starts without stealth injection.
- `STEALTH_ENGINE=local` resolves modules before navigation.
- Module selection is deterministic.
- Legacy and local engines cannot share one context.
- Patch-set and profile IDs are logged.
- Local bundle hash is available.
- Invalid configuration fails before navigation.
- Browser contexts close on success and failure.
- Shadow mode cannot access quota state or Telegram notifications.
- No existing stealth module is modified.
- No experiment output is regenerated.
- Rollback from local to legacy works without code regeneration.

## Final architecture decision

The production bot should depend on a stable `StealthEngine` abstraction.

```text
playwright-stealth
      ↓
LegacyStealthEngine
      ↓
ShadowStealthEngine
      ↓
LocalStealthEngine
      ↓
LocalStealthEngine as default
      ↓
Legacy dependency retired
```

The local Stealth Framework should become production-default only after
context-level installation, profile isolation, patch-set versioning, shadow
validation, and tested rollback are available.

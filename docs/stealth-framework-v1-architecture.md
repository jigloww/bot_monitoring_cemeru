# Stealth Framework v1

## Technical Architecture Review and Migration Blueprint

**Project:** `bot_monitoring_cemeru`  
**Document status:** Proposed architecture blueprint  
**Scope:** Browser fingerprint consistency research framework  
**Last reviewed:** 2026-08-02  

> In this document, "stealth" means a modular consistency layer for controlled
> and authorized browser fingerprint experiments. It is not intended to bypass
> website protection or violate any website's Terms of Service.

---

## 1. Executive Summary

The repository already contains a useful browser fingerprint analysis pipeline,
but several responsibilities are still tightly coupled:

- The comparator also owns the knowledge base and recommendations.
- The scorer imports the comparator's internal constants and helpers.
- The patch generator performs classification, policy decisions, executable
  JavaScript generation, report rendering, and file deployment.
- The registry records file names but does not resolve semantic dependencies.
- The loader primarily concatenates JavaScript strings.
- Domain-specific modules are not yet implemented.
- Generated patches are executable code instead of versioned data.
- The validator measures global before/after changes without module ownership.
- `test_stealth.py` currently tests the legacy generated script path, rather
  than the complete registry and module lifecycle.

Stealth Framework v1 should adopt the following data flow:

```text
FINGERPRINT OBSERVATION
        |
        v
NORMALIZATION
        |
        v
COMPARISON
        |
        v
PATCH PLANNING
        |
        v
GENERATED DATA
        |
        v
REGISTRY RESOLUTION
        |
        v
LOADER + VALIDATION
        |
        v
MODULE EXECUTION
        |
        v
FINGERPRINT VALIDATION
```

The central architectural change is:

> The generator produces desired-state data and evidence. Domain modules own
> the implementation used to interpret and apply that data.

This change allows modules to evolve independently and prevents the patch
generator from becoming a large JavaScript code generator.

---

## 2. Goals and Non-Goals

### 2.1 Goals

- Compare fingerprints produced by different browser environments.
- Measure fingerprint stability and consistency.
- Separate stable fields from naturally volatile fields.
- Support repeatable Playwright experiments.
- Provide one implementation module per browser domain.
- Generate strict, versioned, auditable JSON data.
- Resolve module dependencies deterministically.
- Report module load, apply, validation, and regression results.
- Preserve compatibility with the current pipeline during migration.
- Allow modules to be enabled, disabled, selected, or tested independently.

### 2.2 Non-goals

- Bypassing website protection.
- Automating challenge solving.
- Optimizing specifically for a third-party anti-bot implementation.
- Copying every dynamic value from one reference machine.
- Generating arbitrary executable JavaScript from fingerprint differences.
- Applying experimental modules automatically in the monitoring bot.

---

## 3. Current Architecture Audit

### 3.1 Current dependency graph

```text
tools/fingerprint_dump.py
        |
        | produces fingerprint JSON
        v
tools/compare_fingerprint.py
        +-- flatten()
        +-- vals_equal()
        +-- KB
        +-- CATEGORY_ORDER
        +-- report rendering
               |
       +-------+--------+
       |                |
       v                v
browser_score.py   patch_generator.py
       |                |
       |                +-- classification rules
       |                +-- JavaScript generator
       |                +-- Python generator
       |                +-- report generators
       |                +-- stealth/generated writer
       |
       v
patch_validator.py
       +-- comparator helpers
       +-- browser_score

stealth/apply.py
       +-- loader.py
       |    +-- runtime/*.js
       |    +-- modules/*.js
       |    +-- generated/patches_init.js
       |
       +-- registry.py

tools/test_stealth.py
       +-- tools/fingerprint_dump._JS
       +-- stealth.apply_generated()
```

### 3.2 Comparator coupling

`tools/compare_fingerprint.py` currently owns:

- Recursive flattening.
- Value comparison.
- The fingerprint knowledge base.
- Category mapping.
- Recommendations.
- Priority metadata.
- Text, JSON, Markdown, and HTML rendering.
- CLI parsing.

`browser_score.py`, `patch_generator.py`, and `patch_validator.py` import these
internal details directly. A change to comparison behavior can therefore affect
scoring, generation, and validation at the same time.

Recommended separation:

```text
fingerprint/models.py
fingerprint/schema.py
fingerprint/normalize.py
fingerprint/compare.py
fingerprint/knowledge.py
fingerprint/render.py
```

The current CLI should remain as a compatibility wrapper.

### 3.3 Patch generator coupling

The current patch generator performs too many unrelated operations:

- Classifies differences.
- Maintains patchable object whitelists.
- Maintains dynamic and readonly prefix lists.
- Selects implementation strategies.
- Renders JavaScript literals.
- Generates JavaScript.
- Generates Python wrappers.
- Generates reports.
- Writes runtime artifacts.

In v1, the patch generator should only:

1. Read a normalized comparison report.
2. Route each difference to an owning domain.
3. Classify stability and confidence.
4. Produce desired-state data and evidence.
5. Retain unsupported records for auditability.
6. Write a versioned patch set.

It should not know about `Object.defineProperty`, Proxy implementation, function
wrapping, or Playwright init-script syntax.

### 3.4 Registry limitations

The current registry records:

- Module name.
- File path.
- Description.
- Enabled state.
- A simple status string.

It does not yet represent:

- Required dependencies.
- Optional dependencies.
- Version constraints.
- `before` and `after` ordering.
- Conflicts.
- Owned fingerprint paths.
- Required runtime capabilities.
- Generated-data schemas.
- Cycle detection.
- A deterministic resolution plan.
- Module failure policy.

The registry also reports navigator, window, and screen as active based on the
`enabled` flag even though their JavaScript files are currently absent.

### 3.5 Loader limitations

The current loader reads files and combines their source. It does not yet
validate:

- Module manifests.
- Generated JSON schemas.
- File hashes.
- Runtime and module version compatibility.
- Dependency graphs.
- Duplicate ownership.
- Module conflicts.
- Required generated data.
- Runtime capabilities.
- Structured failure states.

### 3.6 Apply API limitations

The current `apply_stealth(..., modules=...)` signature accepts a module list,
but that list is not connected to registry resolution. The context-level apply
function similarly accepts keyword arguments that are currently unused.

`apply_modules()` adds several init scripts separately. The framework should
not depend on the evaluation order of multiple scripts. The recommended design
assembles one deterministic in-memory bundle while keeping module source files
independent.

### 3.7 Test and validation limitations

`test_stealth.py` currently calls the legacy `apply_generated()` path. It does
not validate:

- Manifest discovery.
- Module selection.
- Dependency ordering.
- Runtime capability resolution.
- Module data schema validation.
- Partial failure behavior.
- Module-level results.

The validator currently reports global improved, regressed, and unchanged
fields. It does not identify which module owned a field or caused a regression.

### 3.8 Existing strengths

- The real Chrome and Playwright collectors use the same fingerprint payload.
- Shared tool utilities already reduce duplicated CLI/browser logic.
- Apply, loader, and registry responsibilities are represented by separate files.
- Runtime helpers provide a starting point for shared browser-side behavior.
- Generated scripts are already isolated under `stealth/generated/`.
- The validator already models improved and regressed values.
- The comparator supports recursive structures and multiple report formats.
- The scorer already distinguishes category and weighted scores.
- The existing pipeline can be preserved behind a legacy adapter.

---

## 4. Stealth Framework v1 Design Principles

### 4.1 Separate data from executable code

Generated files must contain data only.

Generated JSON must not contain:

- JavaScript expressions.
- Function bodies.
- Arbitrary executable templates.
- Python source.
- Object paths intended for `eval`.
- Any other executable content.

Domain modules are the only components allowed to implement browser-side
behavior.

### 4.2 Explicit module ownership

Every fingerprint path has one primary owner:

| Fingerprint path | Primary owner |
|---|---|
| `navigator.*` | navigator |
| `window.*` | window |
| `screen.*` | screen |
| `chrome.*` | chrome |
| `permissions.*` | permissions |
| `speech.*` | speech |
| `battery.*` | battery |
| `performance.*` | performance |
| `webgl.*`, `webgl2.*` | webgl |

Modules may read other domains for validation but must not mutate them without
declared ownership.

### 4.3 Deterministic execution

Module order is resolved by:

1. Required dependencies.
2. `before` and `after` constraints.
3. Priority.
4. Module name as a stable tie-breaker.

Priority never overrides a hard dependency.

### 4.4 Version every boundary

The following contracts require explicit versions:

- Fingerprint schema.
- Comparison report schema.
- Scoring policy.
- Patch-set schema.
- Module manifest schema.
- Per-module data schema.
- Runtime API.
- Module API.
- Validation report schema.

### 4.5 Avoid direct module-to-module imports

Modules interact through:

- A shared immutable environment profile.
- Runtime services.
- Declared capabilities.
- Registry dependencies.
- Cross-module invariant validation.

This prevents navigator, for example, from becoming an informal dependency for
every other module.

### 4.6 Strict tests and configurable integration

Recommended modes:

- `strict`: required module or schema failure stops bundle creation.
- `warn`: optional module failures are reported and skipped.
- `dry-run`: resolve and validate without applying anything.
- `inspect`: enable test-only diagnostic collection.

CI and controlled experiments should use strict mode.

---

## 5. High-Level Blueprint

```text
+-------------------------------------------------------------+
|                    ANALYSIS PIPELINE                        |
|                                                             |
| Fingerprint Collector                                       |
|        |                                                    |
|        v                                                    |
| Normalizer                                                  |
|        |                                                    |
|        v                                                    |
| Comparator                                                  |
|        |                                                    |
|        v                                                    |
| Consistency Scorer                                          |
|        |                                                    |
|        v                                                    |
| Patch Planner / Generator                                   |
|        |                                                    |
|        v                                                    |
| Versioned Generated Data                                    |
+-----------------------+-------------------------------------+
                        |
                        v
+-------------------------------------------------------------+
|                  STEALTH FRAMEWORK v1                       |
|                                                             |
| apply.py                                                    |
|    |                                                        |
|    v                                                        |
| loader.py                                                   |
|    +-- load profile                                         |
|    +-- load patch-set manifest                              |
|    +-- validate module data                                 |
|    +-- request registry resolution                          |
|             |                                               |
|             v                                               |
| registry.py                                                 |
|    +-- dependency graph                                     |
|    +-- ordering                                             |
|    +-- version validation                                   |
|    +-- enable/optional/experimental policy                  |
|             |                                               |
|             v                                               |
| bundle builder                                              |
|    +-- runtime core                                         |
|    +-- generated data injection                             |
|    +-- selected module factories                            |
|    +-- deterministic boot                                   |
|             |                                               |
|             v                                               |
| Playwright BrowserContext.add_init_script()                 |
|             |                                               |
|             v                                               |
| Browser                                                     |
+-----------------------+-------------------------------------+
                        |
                        v
+-------------------------------------------------------------+
|                     VALIDATION                              |
|                                                             |
| Patched Fingerprint                                         |
|        |                                                    |
|        v                                                    |
| Comparator + Scorer                                         |
|        |                                                    |
|        v                                                    |
| Module-aware Validator                                      |
|        |                                                    |
|        v                                                    |
| Promotion / Rejection Report                                |
+-------------------------------------------------------------+
```

### 5.1 Important runtime constraint

Browser-side JavaScript cannot directly read repository JSON files. The correct
flow is:

```text
Python loader
    +-- reads navigator.json
    +-- validates its schema
    +-- reads navigator module source
    +-- injects validated data into an in-memory bundle
```

Using `fetch()` from the page is not recommended because it is origin-dependent,
asynchronous, affected by CSP, observable as network traffic, and may execute
too late.

### 5.2 Modular source, single execution bundle

The framework should avoid a permanently generated giant JavaScript file.
However, the loader should assemble one deterministic in-memory init bundle for
Playwright.

This preserves:

- Independent module source files.
- Per-module tests and documentation.
- Deterministic runtime order.
- A single early init script.
- Centralized failure reporting.

---

## 6. Recommended Folder Structure

```text
stealth/
|-- __init__.py
|-- apply.py
|-- loader.py
|-- registry.py
|-- graph.py
|-- bundle.py
|-- models.py
|-- errors.py
|
|-- schemas/
|   |-- module-manifest.schema.json
|   |-- patch-set.schema.json
|   |-- profile.schema.json
|   |-- navigator.schema.json
|   |-- window.schema.json
|   |-- screen.schema.json
|   |-- chrome.schema.json
|   |-- permissions.schema.json
|   |-- speech.schema.json
|   |-- battery.schema.json
|   |-- performance.schema.json
|   `-- webgl.schema.json
|
|-- runtime/
|   |-- bootstrap.js
|   |-- descriptors.js
|   |-- functions.js
|   |-- types.js
|   |-- clock.js
|   |-- diagnostics.js
|   `-- invariants.js
|
|-- modules/
|   |-- navigator/
|   |   |-- module.json
|   |   |-- index.js
|   |   `-- README.md
|   |-- window/
|   |-- screen/
|   |-- chrome/
|   |-- permissions/
|   |-- speech/
|   |-- battery/
|   |-- performance/
|   `-- webgl/
|
|-- generated/
|   |-- active.json
|   |-- sets/
|   |   `-- <patch-set-id>/
|   |       |-- manifest.json
|   |       |-- profile.json
|   |       |-- navigator.json
|   |       |-- window.json
|   |       |-- screen.json
|   |       |-- chrome.json
|   |       |-- permissions.json
|   |       |-- speech.json
|   |       |-- battery.json
|   |       |-- performance.json
|   |       `-- webgl.json
|   |
|   |-- patches_init.js       # legacy during migration
|   |-- patches.json          # legacy during migration
|   `-- patches.py            # legacy during migration
|
`-- legacy/
    `-- adapter.py
```

Directory-per-module is preferred because each domain will eventually need a
manifest, implementation, tests, fixtures, and documentation.

---

## 7. End-to-End Data Flow

### 7.1 Generation flow

```text
fingerprint_real.json
fingerprint_playwright.json
        |
        v
Normalizer
        +-- normalize types
        +-- identify volatile fields
        +-- preserve semantic arrays and objects
        +-- assign schema version
        |
        v
Comparator
        +-- value differences
        +-- missing fields
        +-- type mismatches
        +-- stable/volatile classification
        |
        v
Patch Planner
        +-- route key to domain
        +-- assess confidence
        +-- mark supported/unsupported
        +-- retain evidence
        |
        v
Patch-Set Writer
        +-- manifest.json
        +-- profile.json
        +-- navigator.json
        +-- window.json
        `-- other domain files
```

### 7.2 Runtime flow

```text
apply_stealth(page, patch_set=..., modules=...)
        |
        v
Loader.load_request()
        +-- requested modules
        +-- patch-set identifier
        +-- strict/warn mode
        +-- experimental flags
        |
        v
Registry.resolve()
        +-- enabled filtering
        +-- dependency expansion
        +-- version checks
        +-- conflict checks
        +-- topological sorting
        `-- ResolutionPlan
        |
        v
Loader.load_plan()
        +-- runtime source
        +-- module manifests
        +-- module source
        +-- generated data
        +-- JSON schema validation
        `-- hash validation
        |
        v
BundleBuilder
        +-- bootstrap runtime
        +-- inject immutable profile
        +-- inject per-module data
        +-- register module factories
        `-- boot in resolved order
        |
        v
context.add_init_script(bundle)
        |
        v
Browser document starts
        |
        v
Runtime boot
        +-- module.validate()
        +-- module.apply()
        +-- invariant checks
        `-- inspect-mode diagnostics
```

### 7.3 Validation flow

```text
Before fingerprint
After fingerprint
Patch-set manifest
ResolutionPlan
LoadReport
        |
        v
Module-aware Validator
        +-- global consistency delta
        +-- target fields improved
        +-- target fields unchanged
        +-- owned fields regressed
        +-- non-owned fields regressed
        +-- invariant violations
        `-- module failures
        |
        v
ValidationReport
        +-- accepted
        +-- rejected
        `-- needs_review
```

---

## 8. Shared Module Contract

Each JavaScript domain module follows the same conceptual contract:

```javascript
runtime.registerModule({
  name: "navigator",
  version: "1.0.0",

  validate(context, data) {
    // Return data and environment validation issues.
  },

  apply(context, data) {
    // Mutate only domain-owned paths.
    // Return applied, skipped, warning, and error records.
  },

  verify(context, data) {
    // Optional module-local invariant checks.
  }
});
```

The implementation may use a factory/IIFE registration format rather than
native ES modules, because Playwright init scripts are easier to assemble in a
self-contained bundle.

### 8.1 Runtime context

Modules receive a limited context:

```text
context.profile
context.moduleData
context.services.descriptors
context.services.functions
context.services.types
context.services.clock
context.services.diagnostics
```

They do not receive filesystem or unrestricted loader access.

### 8.2 Module result

```json
{
  "module": "navigator",
  "version": "1.0.0",
  "status": "applied",
  "applied": ["navigator.webdriver", "navigator.languages"],
  "skipped": ["navigator.userAgentData"],
  "errors": [],
  "warnings": []
}
```

Normal mode should not expose a persistent diagnostic global. Inspect mode can
run test-only post-init verification so that diagnostics do not become part of
the normal browser surface.

---

## 9. Domain Module Designs

### 9.1 Navigator

**Responsibility**

- Direct navigator properties.
- Languages and language.
- Platform and vendor.
- Hardware concurrency and device memory.
- Webdriver state for controlled consistency experiments.
- UA metadata only when the complete identity profile is consistent.

**Dependencies**

- Required: runtime core, descriptors, and types.
- Optional: shared identity profile and function facade.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "navigator",
  "desired": {
    "platform": "Win32",
    "vendor": "Google Inc.",
    "languages": ["en-US", "en", "id"],
    "hardwareConcurrency": 12,
    "deviceMemory": 8,
    "webdriver": false
  },
  "evidence": [],
  "unsupported": []
}
```

**Registry metadata**

```text
owns: navigator.*
priority: 20
experimental: false
```

**Primary risk:** UA, UA-CH, platform, locale, and request headers may become
internally inconsistent if patched independently.

### 9.2 Window

**Responsibility**

- Inner and outer dimensions.
- Device pixel ratio.
- Approved direct window properties.
- It does not own `screen.*`.

**Dependencies**

- Runtime descriptors.
- Shared viewport profile.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "window",
  "desired": {
    "innerWidth": 1024,
    "innerHeight": 720,
    "outerWidth": 1050,
    "outerHeight": 798,
    "devicePixelRatio": 1
  }
}
```

**Registry metadata**

```text
owns: window.*
priority: 30
before: screen
```

**Primary risk:** values can disagree with the actual Playwright viewport and
browser window configuration.

### 9.3 Screen

**Responsibility**

- Width and height.
- Available width and height.
- Color and pixel depth.
- Orientation surface.
- Display/viewport invariant checks.

**Dependencies**

- Runtime descriptors.
- Shared display profile.
- Soft ordering after window.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "screen",
  "desired": {
    "width": 1920,
    "height": 1080,
    "availWidth": 1920,
    "availHeight": 1040,
    "colorDepth": 24,
    "pixelDepth": 24,
    "orientation": {
      "type": "landscape-primary",
      "angle": 0
    }
  }
}
```

**Primary risk:** orientation is a complex object with descriptor and prototype
behavior, rather than a simple primitive value.

### 9.4 Chrome

**Responsibility**

- `window.chrome`.
- `chrome.runtime`.
- `chrome.app`.
- `chrome.loadTimes`.
- `chrome.csi`.

**Dependencies**

- Runtime functions.
- Runtime descriptors.
- Runtime clock/time-origin service.
- Soft ordering after performance when that module is selected.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "chrome",
  "desired": {
    "present": true,
    "runtime": {
      "present": true,
      "properties": []
    },
    "loadTimes": {
      "enabled": true,
      "model": "runtime-clock"
    },
    "csi": {
      "enabled": true,
      "model": "runtime-clock"
    }
  }
}
```

The data describes the expected surface, not function source code.

**Primary risk:** name, prototype, descriptors, exceptions, native function
appearance, and dynamic timing must remain consistent.

### 9.5 Permissions

**Responsibility**

- `navigator.permissions.query()`.
- Permission-name state mapping.
- Promise behavior.
- PermissionStatus-like results.
- Native fallback behavior.

**Dependencies**

- Runtime functions, types, and descriptors.
- Soft ordering after navigator.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "permissions",
  "desired": {
    "notifications": "default",
    "geolocation": "prompt",
    "camera": "prompt",
    "microphone": "prompt"
  },
  "unknown_permission_policy": "native"
}
```

**Primary risk:** permission states depend on origin and browser-context policy.

### 9.6 Speech

**Responsibility**

- Speech synthesis availability.
- Voice catalog.
- `getVoices()`.
- Voice loading timing.
- Optional `voiceschanged` behavior.

**Dependencies**

- Runtime functions and types.
- Optional locale profile and navigator-language consistency.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "speech",
  "desired": {
    "enabled": true,
    "voices": [
      {
        "name": "Example Voice",
        "lang": "en-US",
        "localService": true,
        "default": true,
        "voiceURI": "Example Voice"
      }
    ],
    "load_model": "deferred"
  }
}
```

**Primary risk:** voices depend heavily on OS resources and browser installation.
Environment provisioning should be preferred over synthetic data where possible.

### 9.7 Battery

**Responsibility**

- `navigator.getBattery` availability.
- Promise behavior.
- BatteryManager-like surface.
- Charging, level, and timing values.
- Optional event behavior.

**Dependencies**

- Runtime functions and types.
- Soft ordering after navigator.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "battery",
  "desired": {
    "available": true,
    "charging": true,
    "level": 1,
    "chargingTime": {
      "$type": "number",
      "value": "positive_infinity"
    },
    "dischargingTime": {
      "$type": "number",
      "value": "positive_infinity"
    }
  }
}
```

**Primary risk:** battery data is dynamic and exact snapshots should not be used
as default patch targets.

### 9.8 Performance

**Responsibility**

- Stable performance surface.
- Optional memory object shape.
- Relative timing consistency.
- Dynamic-value policy.

**Dependencies**

- Runtime clock, descriptors, and functions.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "performance",
  "desired": {
    "memory": {
      "available": true,
      "jsHeapSizeLimit": 4294705152
    },
    "timing_policy": "native-relative",
    "resource_count_policy": "native"
  }
}
```

**Primary risk:** frozen or copied timestamps produce impossible timing sequences.
The module must work with invariants and relative values instead.

### 9.9 WebGL

**Responsibility**

- WebGL and WebGL2 surface selected for an experiment.
- Parameter observations.
- Extension availability.
- Limits and renderer profile.
- Cross-consistency validation.

**Dependencies**

- Runtime functions, types, and proxy/descriptor support.
- Optional future canvas/GPU profile capability.

**Input**

```json
{
  "schema_version": "1.0",
  "module": "webgl",
  "desired": {
    "webgl1": {
      "available": true,
      "vendor": "WebKit",
      "renderer": "WebKit WebGL",
      "unmaskedVendor": "Google Inc. (Intel)",
      "unmaskedRenderer": "ANGLE (...) ",
      "limits": {},
      "extensions": []
    },
    "webgl2": {
      "available": true
    }
  }
}
```

**Registry metadata**

```text
owns: webgl.*, webgl2.*
priority: 90
experimental: true
enabled_by_default: false
```

**Primary risk:** renderer, extensions, limits, and rendering results can become
mutually inconsistent. Environment or GPU configuration should be evaluated
before browser-side transformation.

---

## 10. Registry Design

### 10.1 Module manifest

Example `modules/screen/module.json`:

```json
{
  "manifest_version": "1.0",
  "name": "screen",
  "version": "1.0.0",
  "entrypoint": "index.js",
  "data_schema": "../../schemas/screen.schema.json",
  "priority": 30,
  "depends_on": [
    {
      "name": "runtime.descriptors",
      "version": ">=1.0,<2.0"
    }
  ],
  "optional_dependencies": ["window"],
  "before": [],
  "after": ["window"],
  "enabled_by_default": true,
  "optional": false,
  "experimental": false,
  "owns": ["screen.*"],
  "reads": ["window.innerWidth", "window.innerHeight"],
  "capabilities": ["screen.consistency"],
  "requires_capabilities": ["runtime.descriptors"],
  "conflicts": [],
  "supported_patch_schema": "1.x"
}
```

### 10.2 Field semantics

- `priority`: deterministic tie-breaker among modules currently ready to run.
- `depends_on`: hard dependencies; missing or incompatible dependencies fail.
- `optional_dependencies`: used when present but not required.
- `before`/`after`: soft ordering constraints if both modules are selected.
- `optional`: controls whether a module failure can be tolerated.
- `experimental`: requires an explicit enable flag.
- `enabled_by_default`: default profile selection.
- `owns`: paths the module may mutate.
- `reads`: paths read only for validation.
- `capabilities`: services or semantic behavior the module provides.
- `requires_capabilities`: required runtime/module capabilities.
- `conflicts`: modules or ownership sets that cannot coexist.

### 10.3 Registry API

```python
registry.discover(modules_dir)
registry.register(manifest)
registry.get(name)
registry.list()
registry.validate()
registry.resolve(selection, profile, flags) -> ResolutionPlan
```

The registry manages metadata and resolution only. It does not read JavaScript
source or build a bundle.

### 10.4 Resolution algorithm

```text
1. Discover manifests
2. Validate manifest schemas
3. Reject duplicate module names
4. Apply profile and CLI enable/disable filters
5. Reject unapproved experimental modules
6. Expand hard dependencies
7. Add available optional dependencies
8. Validate version constraints
9. Validate conflicts and overlapping ownership
10. Build graph edges
11. Detect cycles
12. Topologically sort
13. Apply priority and name tie-breakers
14. Produce ResolutionPlan
```

### 10.5 Resolution plan

```json
{
  "plan_version": "1.0",
  "selected": ["navigator", "window", "screen"],
  "ordered": ["navigator", "window", "screen"],
  "skipped": [
    {
      "module": "webgl",
      "reason": "experimental_not_enabled"
    }
  ],
  "warnings": [],
  "errors": [],
  "ownership": {
    "navigator.*": "navigator",
    "window.*": "window",
    "screen.*": "screen"
  }
}
```

---

## 11. Loader Design

### 11.1 Responsibilities

- Read runtime source.
- Read module manifests and source.
- Read the patch-set manifest.
- Read per-module generated data.
- Validate schemas and hashes.
- Request a resolution plan from the registry.
- Build a deterministic in-memory bundle.
- Return a structured load report.
- Never decide fingerprint patch policy.

### 11.2 Proposed API

```python
request = LoadRequest(
    patch_set="active",
    modules=["navigator", "window", "screen"],
    strict=True,
    experimental=False,
    inspect=False,
)

bundle, report = loader.load(request)
```

### 11.3 Lazy loading

Lazy loading means Python reads only selected module data and source. It does
not mean modules are loaded after navigation. Selected modules must still be
present in the init bundle before page scripts execute.

### 11.4 Error classification

The loader should distinguish:

- Manifest errors.
- Missing source.
- Missing generated data.
- Schema errors.
- Hash mismatches.
- Unsupported schema versions.
- Missing dependencies.
- Version mismatches.
- Dependency cycles.
- Ownership conflicts.
- Bundle construction errors.

Required errors must not be silently swallowed.

### 11.5 Load report

```json
{
  "status": "success_with_warnings",
  "patch_set": "ps-20260802-001",
  "runtime_version": "1.0.0",
  "modules": [
    {
      "name": "navigator",
      "version": "1.0.0",
      "status": "loaded",
      "data_file": "navigator.json",
      "data_hash": "..."
    }
  ],
  "skipped": [],
  "warnings": [],
  "errors": [],
  "bundle_hash": "..."
}
```

### 11.6 Data integrity

The loader should:

- Reject paths outside the selected patch-set directory.
- Limit generated JSON size.
- Verify SHA-256 hashes declared in the manifest.
- Reject executable fields and unknown strategy expressions.
- Reject non-standard JSON.
- Avoid exposing host paths or secrets in the browser bundle.
- Support atomic patch-set activation.

---

## 12. Generated Patch-Set Design

### 12.1 Immutable patch sets

Generated runs should use immutable directories:

```text
stealth/generated/sets/ps-20260802-001/
```

`active.json` becomes a small pointer:

```json
{
  "patch_set": "ps-20260802-001"
}
```

This supports rollback, comparison, reproducibility, and audit history.

### 12.2 Patch-set manifest

```json
{
  "format_version": "1.0",
  "patch_set_id": "ps-20260802-001",
  "generated_at": "2026-08-02T22:00:00+07:00",
  "generator_version": "1.0.0",
  "source": {
    "reference_file": "fingerprint_real.json",
    "reference_sha256": "...",
    "test_file": "fingerprint_playwright.json",
    "test_sha256": "...",
    "fingerprint_schema": "1.0"
  },
  "profile": {
    "path": "profile.json",
    "sha256": "..."
  },
  "modules": {
    "navigator": {
      "path": "navigator.json",
      "sha256": "...",
      "schema_version": "1.0",
      "candidate_count": 6
    },
    "window": {
      "path": "window.json",
      "sha256": "...",
      "schema_version": "1.0",
      "candidate_count": 4
    }
  },
  "summary": {
    "total_diffs": 180,
    "stable_diffs": 42,
    "generated_candidates": 18,
    "unsupported": 24,
    "volatile_skipped": 114
  }
}
```

### 12.3 Shared environment profile

```json
{
  "schema_version": "1.0",
  "identity": {
    "os_family": "windows",
    "platform": "Win32",
    "browser_family": "chromium",
    "locale": "id-ID",
    "languages": ["id-ID", "id", "en-US", "en"]
  },
  "display": {
    "viewport_width": 1024,
    "viewport_height": 720,
    "device_pixel_ratio": 1
  },
  "hardware": {
    "logical_processors": 12,
    "device_memory_gb": 8
  }
}
```

The shared profile is the canonical source for values that cross domain
boundaries. Per-domain JSON remains independent, while the loader validates
cross-domain invariants against the profile.

### 12.4 Desired-state data

Generated records should contain observations and desired state, not runtime
instructions:

```json
{
  "path": "navigator.platform",
  "reference": "Win32",
  "observed": "Linux x86_64",
  "desired": "Win32",
  "classification": "stable_value",
  "confidence": 0.98,
  "source_runs": 10
}
```

The navigator module decides if and how this desired value can be applied.

### 12.5 Unsupported records

Unsupported differences must remain in the patch set:

```json
{
  "unsupported": [
    {
      "path": "navigator.userAgentData.brands",
      "reason": "complex_object_requires_manual_profile",
      "reference": [],
      "observed": []
    }
  ]
}
```

This preserves evidence without generating unsafe or invalid code.

### 12.6 Non-finite values

Values such as `Infinity` are not valid portable JSON. Use tagged values:

```json
{
  "$type": "number",
  "value": "positive_infinity"
}
```

Dynamic non-finite values may alternatively remain observational and never
become desired patch data.

---

## 13. Tooling Refactor Blueprint

```text
tools/
|-- fingerprint_dump.py
|-- compare_fingerprint.py       # compatibility CLI
|-- browser_score.py             # compatibility CLI
|-- patch_generator.py           # compatibility CLI
|-- patch_validator.py           # compatibility CLI
|-- test_stealth.py
|
|-- fingerprint/
|   |-- models.py
|   |-- schema.py
|   |-- normalize.py
|   |-- compare.py
|   |-- knowledge.py
|   `-- render.py
|
|-- scoring/
|   |-- models.py
|   |-- policy.py
|   |-- score.py
|   `-- render.py
|
|-- patching/
|   |-- models.py
|   |-- router.py
|   |-- planner.py
|   |-- schemas.py
|   `-- writer.py
|
`-- validation/
    |-- models.py
    |-- module_validator.py
    |-- invariants.py
    `-- render.py
```

### 13.1 Comparator

Separate semantic traversal, value comparison, volatility rules, knowledge,
and rendering. The CLI remains stable and delegates to the new internals.

### 13.2 Scoring

The `cf_risk_score` name should be deprecated because the project measures
fingerprint consistency. Recommended metrics:

- `raw_similarity_score`.
- `stable_consistency_score`.
- `weighted_consistency_score`.
- `schema_coverage`.
- `collector_error_rate`.

A compatibility alias may remain for older reports during migration.

Weights should move from a Python constant to a versioned scoring-policy file.

### 13.3 Validator

The validator should accept:

```text
--ref
--before
--after
--patch-set
--load-report
```

It should report per-domain results:

```json
{
  "navigator": {
    "targeted": 6,
    "improved": 4,
    "unchanged": 1,
    "regressed": 1,
    "foreign_regressions": 0,
    "status": "needs_review"
  }
}
```

### 13.4 Test harness

Target CLI:

```text
python tools/test_stealth.py \
  --engine v1 \
  --patch-set active \
  --modules navigator window screen \
  --strict \
  --inspect
```

Migration modes:

```text
--engine legacy
--engine v1
--engine compare
```

Compare mode should use separate browser instances so legacy and v1 scripts do
not mutate the same page.

---

## 14. Target Dependency Graph

```text
                         +------------------+
                         | runtime.bootstrap|
                         +--------+---------+
                                  |
            +---------------------+---------------------+
            |                     |                     |
            v                     v                     v
 runtime.descriptors      runtime.functions       runtime.types
            |                     |                     |
            +--------------+      +--------------+      |
            |              |      |              |      |
            v              v      v              v      v
       navigator        window  chrome       permissions battery
                            |
                            v
                          screen

 runtime.clock ------------+-----------------------------+
                           |                             |
                           v                             v
                     performance                      chrome

 shared.profile -----------+-----------+-----------+-----------+
                           |           |           |           |
                           v           v           v           v
                       navigator     window      screen       speech

 runtime.proxy/functions/types
                           |
                           v
                         webgl
                    [experimental]
```

Most relationships should use shared profile data or soft ordering rather than
hard module imports.

---

## 15. Implementation Roadmap

Effort estimates assume one developer already familiar with the repository.

### Sprint 0: Contracts and safety net

**Targets**

- Shared models.
- Schema versions.
- Module and patch-set manifest schemas.
- ResolutionPlan and LoadReport models.
- Unit tests around current comparator, scorer, and generator.
- Frozen legacy fixtures.

**Dependencies:** none.  
**Risk:** designing an unnecessarily complex schema too early.  
**Complexity:** high, approximately 5-8 engineering days.  
**Outcome:** stable v1 contracts without changing legacy runtime behavior.

### Sprint 1: Registry, loader core, and navigator vertical slice

**Targets**

- Dependency graph and cycle detection.
- Version and conflict validation.
- Deterministic ordering.
- V1 bundle builder.
- Navigator schema, manifest, module, and generated data.
- V1 test-engine option.

**Dependencies:** Sprint 0.  
**Risks:** descriptors, identity consistency, and duplicate legacy ownership.  
**Complexity:** high, 8-12 days.  
**Outcome:** one complete domain operates without generated executable JS.

### Sprint 2: Window

**Targets:** window schema/module, viewport profile, ownership validation.  
**Dependencies:** descriptors, profile, v1 loader.  
**Risk:** differences caused by headed/headless browser decoration.  
**Complexity:** medium, 3-5 days.  
**Outcome:** window fields can be selected and tested independently.

### Sprint 3: Screen

**Targets:** screen schema/module, orientation, window/screen invariants.  
**Dependencies:** Sprint 2 recommended; not necessarily a hard dependency.  
**Risk:** complex orientation surface and environment-specific available sizes.  
**Complexity:** medium, 3-5 days.  
**Outcome:** display consistency is validated as one profile.

### Sprint 4: Chrome

**Targets:** chrome surface, runtime/app objects, function facade, clock models.  
**Dependencies:** functions, descriptors, clock capabilities.  
**Risk:** semantic and timing inconsistency.  
**Complexity:** high, 7-10 days.  
**Outcome:** Chrome-specific surface is owned by one module.

### Sprint 5: Permissions

**Targets:** permission map, Promise behavior, native fallback, origin policy.  
**Dependencies:** functions/types and navigator ordering.  
**Risk:** state depends on origin and browser context.  
**Complexity:** high, 7-10 days.  
**Outcome:** Permissions API can be tested through a scenario matrix.

### Sprint 6: Speech

**Targets:** voice schema, observation mode, optional catalog, loading model.  
**Dependencies:** functions/types and locale profile.  
**Risk:** OS resources and asynchronous loading.  
**Complexity:** high, 7-12 days.  
**Outcome:** environment gaps and module-supported gaps are distinguishable.

### Sprint 7: Battery

**Targets:** tagged numbers, Promise API, object model, dynamic policy.  
**Dependencies:** functions/types and strict JSON handling.  
**Risk:** treating a dynamic snapshot as a stable target.  
**Complexity:** medium-high, 4-7 days.  
**Outcome:** battery observations use portable JSON and explicit policy.

### Sprint 8: Performance

**Targets:** relative timing, clock service, memory policy, dynamic exclusions.  
**Dependencies:** clock runtime and Chrome timing contract.  
**Risk:** impossible or frozen timing sequences.  
**Complexity:** high, 7-12 days.  
**Outcome:** performance consistency is measured through invariants.

### Sprint 9: WebGL

**Targets:** profile schema, observation mode, approved parameters, invariants.  
**Dependencies:** mature function/proxy runtime and validation framework.  
**Risk:** very high cross-surface inconsistency.  
**Complexity:** very high, 10-15 days.  
**Outcome:** an explicit experimental module with measurable limitations.

### Sprint 10: Consolidation

**Targets**

- Architecture documentation.
- Architecture decision records.
- CI matrix.
- Golden fixtures.
- Module authoring guide.
- Legacy deprecation policy.
- Version 1 release readiness.

**Complexity:** medium-high, 5-8 days.

---

## 16. Bug and Technical Debt Register

| Priority | Finding | Cause | Impact | Compatible remediation |
|---|---|---|---|---|
| P0 | Registry reports modules active when their files are absent | Active is based on `enabled` only | Misleading framework status | Report available, enabled, resolved, and loaded separately |
| P0 | `apply_stealth(modules=...)` ignores selection | Argument is not connected to resolution | Selected-module API is ineffective | Forward selection to `Registry.resolve()` |
| P0 | Context apply ignores keyword options | Scaffold API is unfinished | Callers believe options are supported | Introduce typed ApplyOptions and warn on unknown options |
| P0 | Generated Python can be invalid for arrays containing strings | Manual escaping | Artifact cannot be imported | Stop Python generation in v1; repair only the legacy serializer |
| P0 | Runtime state directory is not created before saving | Direct `write_text()` | First bot start can fail | Create the parent directory inside `save_state()` |
| P1 | Active generated data is empty while reports contain an older patch set | Two artifact generations are unsynchronized | Active patch state is unclear | Introduce immutable patch sets and an active pointer |
| P1 | Generator `--output` does not honor the requested filename | Only the parent directory is used | CLI contract is misleading | Preserve defaults but honor explicit output names |
| P1 | Cookie timeline references `CF_COOKIES` without importing it | Missing import | Runtime NameError | Import the shared constant |
| P1 | Registry silently swallows file errors | Broad error suppression | Missing modules are hidden | Return structured loader errors |
| P1 | Test harness exercises only the legacy generated script | Calls `apply_generated()` | Modules and registry are not tested | Add legacy/v1/compare engine modes |
| P1 | Test output suggests an invalid comparator CLI form | Stale command example | Follow-up command fails | Correct log output without breaking the CLI |
| P1 | Stored patched score regresses | Volatile fields and category bias | Score is not a reliable acceptance gate | Add normalization and stable consistency scoring |
| P1 | Nested KB priority is not inherited consistently | Exact-key lookup in ranking | Nested differences get incorrect priority | Use one shared knowledge lookup function |
| P1 | Reports contain `Infinity` | Python permits non-finite JSON output | Reports are not portable strict JSON | Use tagged values or exclude volatile non-finite targets |
| P1 | Generator remains whitelist-heavy | Implementation policy is embedded in generation | Many differences are discarded | Route all evidence; let modules declare support |
| P1 | No explicit module ownership | Registry stores files only | Duplicate or conflicting mutations | Add ownership and conflict validation |
| P2 | Example interval variable differs from code | Documentation drift | User configuration can be ignored | Support the old alias with a warning |
| P2 | Browser identity and dimensions are hardcoded | Prototype configuration | Environment inconsistency | Move values into experiment profiles |
| P2 | Report names and directories differ from aggregator expectations | Independent CLI evolution | Full report misses existing data | Resolve artifacts through run manifests |
| P2 | Network and cookie artifacts may contain sensitive data | Raw diagnostics are committed | Session/privacy risk | Add redaction and ignore runtime experiment outputs |
| P2 | Comparator owns too many concerns | Incremental growth | High coupling | Add internal packages behind the existing CLI |
| P2 | Broad collector fallbacks hide errors as missing data | Continue-on-error design | Missing fields are misclassified | Include collector error metadata |
| P2 | Legacy terminology emphasizes evasion/risk | Historical naming | Inconsistent with official project goal | Rename to consistency terms with compatibility aliases |

---

## 17. Migration Plan

### Phase 0: Freeze legacy behavior

- Store current inputs and outputs as fixtures.
- Record existing CLI behavior.
- Keep `apply_generated()` unchanged.
- Add tests around current generated artifacts.

**Exit criterion:** the existing pipeline is reproducible in tests.

### Phase 1: Add v1 models and schemas

Add ModuleManifest, PatchSetManifest, ResolutionPlan, LoadReport, validation
models, and JSON schemas without changing runtime behavior.

**Exit criterion:** manually authored v1 fixtures validate successfully.

### Phase 2: Dual-output generator

Add:

```text
--format legacy
--format v1
--format both
```

The initial default should be `both`.

Legacy output remains:

```text
patches_init.js
patches.py
patches.json
```

V1 output becomes:

```text
sets/<patch-set-id>/manifest.json
sets/<patch-set-id>/profile.json
sets/<patch-set-id>/<domain>.json
```

**Exit criterion:** legacy output remains compatible and v1 data is available.

### Phase 3: V1 registry and loader

Introduce a new API:

```python
apply_stealth_v1(...)
```

Keep:

```python
apply_generated(...)
```

**Exit criterion:** registry dry-run produces a deterministic plan.

### Phase 4: Navigator shadow mode

The navigator module loads and validates data but is used only by the research
test harness, not by the monitoring bot.

**Exit criterion:** module-level reports are available.

### Phase 5: Navigator active experiment

The test harness supports legacy and v1 engines. Promotion requires:

- No schema errors.
- No loader/module errors.
- Target fields improve.
- No high-priority foreign regressions.
- Collector completeness does not decrease.

### Phase 6: Migrate one domain at a time

Migration order:

```text
navigator
window
screen
chrome
permissions
speech
battery
performance
webgl
```

Each domain must add:

1. Schema.
2. Manifest.
3. Generator routing.
4. Module implementation.
5. Unit tests.
6. Integration tests.
7. Validation gates.
8. Documentation.

### Phase 7: Hybrid compatibility

When legacy and v1 are both active:

- V1 owns migrated domain paths.
- The legacy adapter removes those paths from its output.
- The loader rejects duplicate ownership.
- Legacy handles only domains not yet migrated.

Legacy and v1 must never modify the same path in one browser instance.

### Phase 8: Change test defaults

After navigator, window, screen, and chrome are stable:

- V1 may become the default test engine.
- Legacy remains selectable.
- `apply_generated()` remains available.

### Phase 9: Deprecate executable generation

After all domains and at least two compatibility release cycles:

- Legacy executable generation emits a deprecation warning.
- Legacy readers remain available for historical patch sets.
- Golden legacy fixtures move to the test suite.
- The active runtime uses module-driven generated data.

---

## 18. Architecture Trade-offs

| Decision | Benefit | Cost | Recommendation |
|---|---|---|---|
| One JSON file per domain | Clear ownership and isolated tests | Requires a manifest and cross-file validation | Adopt |
| Shared `profile.json` | Cross-domain consistency | Adds one data layer | Adopt |
| Directory per module | Scales to manifests, tests, and docs | More files | Adopt as target structure |
| Single in-memory runtime bundle | Deterministic early initialization | Bundle can still be large in memory | Adopt |
| Multiple init scripts | Simple initial implementation | Ordering and bootstrap dependencies are harder | Avoid as the primary contract |
| Manifest-driven registry | Extensible without central code edits | Requires discovery and schema validation | Adopt |
| Hardcoded central registry | Simple | Becomes a maintenance bottleneck | Limit to runtime bootstrap only |
| Strict schema validation | Reproducible and auditable | Early generators fail more often | Strict in tests; tolerant only for optional modules |
| Desired-state generator | Strong separation of concerns | Modules become more sophisticated | Adopt |
| Generator-selected implementation strategy | Simpler module logic | Re-couples generator to JavaScript | Avoid |
| Browser-side lazy loading | Smaller initial source | Late, observable, and non-deterministic | Reject |
| Python-side lazy loading | Reads only selected modules | More loader logic | Adopt |
| Immutable patch sets | Reproducible and easy rollback | Additional disk usage | Adopt |
| Exact reference cloning | Quickly reduces simple diffs | Overfitting and dynamic inconsistency | Avoid |
| Environment provisioning | More natural browser behavior | More deployment complexity | Prefer for fonts, speech, and GPU |
| Generic Proxy framework | Flexible | Can create unrealistic behavior | Use only where a domain requires it |
| Experimental module flag | Safer defaults | Requires profile and CLI policy | Require for high-risk modules |

---

## 19. Priority Order

Recommended implementation order:

1. Schemas and shared models.
2. Registry dependency resolver.
3. Loader and deterministic bundle builder.
4. V1 patch-set writer.
5. Navigator vertical slice.
6. Module-aware validator.
7. Window.
8. Screen.
9. Chrome.
10. Permissions.
11. Speech.
12. Battery.
13. Performance.
14. WebGL.
15. Optional monitoring-bot integration behind a feature flag.

WebGL and Chrome should not be the first modules implemented. They require a
mature registry, runtime contract, validation system, and rollback path.

---

## 20. Definition of Done

Stealth Framework v1 is complete when:

- The v1 generator produces no executable JavaScript.
- Each domain has a manifest, schema, module source, tests, and documentation.
- Registry resolution detects missing dependencies, incompatible versions,
  conflicts, duplicate ownership, and cycles.
- The loader builds a deterministic bundle and structured report.
- Generated data is strict JSON.
- Every patch set has provenance and integrity hashes.
- Module ownership is validated.
- The test harness can select engine, patch set, and modules.
- Validation reports results per module.
- Scoring distinguishes stable consistency from volatile differences.
- The legacy pipeline remains executable during its compatibility period.
- Patch sets can be rolled back without regeneration.
- Experimental modules are disabled by default.
- The monitoring bot does not depend on framework internals.
- Project documentation consistently describes the framework as browser
  fingerprint consistency research tooling.

---

## 21. Architecture Decision Summary

The official v1 direction is:

```text
Patch Generator
    produces versioned DATA
        |
        v
Registry
    resolves module metadata and order
        |
        v
Loader
    validates data and assembles selected source
        |
        v
Domain Modules
    own browser-side behavior
        |
        v
Validator
    measures module targets, regressions, and invariants
```

This architecture changes the project from a monolithic generated-script model
into a module-driven framework while preserving the existing pipeline through a
controlled compatibility layer.

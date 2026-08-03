# Fingerprint Knowledge Graph

## Executive Summary

- Result: **SUCCESS**
- Nodes: **1922**
- Edges: **3798**
- Components: **70**
- Browser launches: **0**
- Network requests: **0**

## Graph Overview

| Metric | Value |
|---|---:|
| Nodes | 1922 |
| Edges | 3798 |
| Fingerprint properties | 880 |
| Tasks | 471 |
| Modules | 12 |

## Centrality

| Node | Degree | Betweenness | Closeness |
|---|---:|---:|---:|
| `feature:category:other` | 0.232 | 0.504 | 0.322 |
| `module:other` | 0.232 | 0.504 | 0.322 |
| `sprint:2` | 0.084 | 0.301 | 0.246 |
| `feature:category:navigator` | 0.100 | 0.290 | 0.243 |
| `module:navigator` | 0.100 | 0.290 | 0.243 |
| `sprint:3` | 0.067 | 0.274 | 0.242 |
| `sprint:4` | 0.085 | 0.251 | 0.243 |
| `property:navigator.platform` | 0.104 | 0.227 | 0.215 |
| `sprint:1` | 0.010 | 0.114 | 0.225 |
| `property:navigator.language` | 0.053 | 0.088 | 0.205 |
| `property:webgl.aliased_point_size_range[1]` | 0.004 | 0.076 | 0.203 |
| `task:OPT-207` | 0.001 | 0.076 | 0.213 |
| `property:canvas.hash` | 0.002 | 0.047 | 0.273 |
| `property:canvas.length` | 0.002 | 0.047 | 0.273 |
| `task:OPT-020` | 0.001 | 0.045 | 0.245 |

## Clusters

Connected components: **70**; strongly connected groups: **2**.

| Component | Size |
|---|---:|
| component:001 | 1848 |
| component:002 | 4 |
| component:003 | 3 |
| component:004 | 1 |
| component:005 | 1 |
| component:006 | 1 |
| component:007 | 1 |
| component:008 | 1 |
| component:009 | 1 |
| component:010 | 1 |
| component:011 | 1 |
| component:012 | 1 |
| component:013 | 1 |
| component:014 | 1 |
| component:015 | 1 |

## Hotspots

- **Most Influential Property**: `property:navigator.userAgent`
- **Most Connected Module**: `Other`
- **Highest Risk Cluster**: `component:001`
- **Highest Roi Cluster**: `OPT-014`
- **Most Critical Dependency Chain**: `[]`
- **Most Frequently Appearing Property**: `property:webgl.aliased_point_size_range[1]`

## Module Analysis

| Module | Properties | Internal density | External deps | Cross links |
|---|---:|---:|---:|---:|
| Chrome | 17 | 0.000 | 85 | 51 |
| Environment | 29 | 0.000 | 66 | 0 |
| Fonts | 26 | 0.000 | 104 | 52 |
| Navigator | 194 | 0.002 | 837 | 2 |
| Other | 445 | 0.000 | 1664 | 0 |
| Performance | 11 | 0.000 | 43 | 21 |
| Permissions | 7 | 0.000 | 28 | 14 |
| Screen | 9 | 0.194 | 163 | 25 |
| Speech | 68 | 0.000 | 269 | 135 |
| Storage | 10 | 0.000 | 40 | 0 |
| WebGL | 53 | 0.000 | 315 | 208 |
| Window | 11 | 0.227 | 124 | 18 |

## Task Impact

| Task | Property | Gain | CF gain | ROI | Risk |
|---|---|---:|---:|---:|---|
| `OPT-014` | `intl.collator.locale` | 0.295 | 0.266 | 0.295 | Low |
| `OPT-015` | `intl.listFormat.locale` | 0.295 | 0.266 | 0.295 | Low |
| `OPT-016` | `intl.numberFormat.locale` | 0.295 | 0.266 | 0.295 | Low |
| `OPT-017` | `timezone.locale` | 0.295 | 0.266 | 0.295 | Low |
| `OPT-018` | `indexeddb.databases[0]` | 0.278 | 0.153 | 0.278 | Low |
| `OPT-019` | `indexeddb.databases[1]` | 0.278 | 0.153 | 0.278 | Low |
| `OPT-022` | `indexeddb.count` | 0.249 | 0.137 | 0.249 | Low |
| `OPT-023` | `storage.localStorage_length` | 0.249 | 0.137 | 0.249 | Low |
| `OPT-024` | `storage.sessionStorage_length` | 0.249 | 0.137 | 0.249 | Low |
| `OPT-025` | `storage.caches_available` | 0.227 | 0.125 | 0.227 | Low |
| `OPT-026` | `storage.cookieStore_available` | 0.227 | 0.125 | 0.227 | Low |
| `OPT-027` | `storage.indexedDB_available` | 0.227 | 0.125 | 0.227 | Low |
| `OPT-028` | `indexeddb` | 0.225 | 0.124 | 0.225 | Low |
| `OPT-029` | `storage` | 0.225 | 0.124 | 0.225 | Low |
| `OPT-030` | `document.cookie_names[0]` | 0.224 | 0.134 | 0.224 | Low |
| `OPT-031` | `document.domain` | 0.224 | 0.134 | 0.224 | Low |
| `OPT-032` | `document.referrer` | 0.224 | 0.134 | 0.224 | Low |
| `OPT-033` | `navigator_own_keys[40]` | 0.224 | 0.134 | 0.224 | Low |
| `OPT-034` | `navigator_own_keys[41]` | 0.224 | 0.134 | 0.224 | Low |
| `OPT-035` | `navigator_own_keys[46]` | 0.224 | 0.134 | 0.224 | Low |

## Recommendations

- Priority nodes: 25
- Learning candidates: 0
- Optimization candidates: 25
- Uncertain relationships: 0

## Validation

- Valid: **True**
- Deterministic ordering: **True**
- Artifact completeness: **True**

## Final Conclusion

The graph is a deterministic, read-only evidence map that can be reused by future planning experiments.

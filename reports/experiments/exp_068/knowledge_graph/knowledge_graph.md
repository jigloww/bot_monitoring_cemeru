# Fingerprint Knowledge Graph

## Executive Summary

- Result: **SUCCESS**
- Nodes: **2111**
- Edges: **5721**
- Components: **45**
- Browser launches: **0**
- Network requests: **0**

## Graph Overview

| Metric | Value |
|---|---:|
| Nodes | 2111 |
| Edges | 5721 |
| Fingerprint properties | 880 |
| Tasks | 471 |
| Modules | 12 |

## Centrality

| Node | Degree | Betweenness | Closeness |
|---|---:|---:|---:|
| `experiment:exp_025` | 0.224 | 0.388 | 0.397 |
| `experiment:exp_023` | 0.224 | 0.374 | 0.395 |
| `experiment:exp_024` | 0.224 | 0.357 | 0.396 |
| `feature:category:other` | 0.211 | 0.260 | 0.309 |
| `module:other` | 0.211 | 0.260 | 0.309 |
| `property:navigator.language` | 0.048 | 0.153 | 0.268 |
| `feature:category:navigator` | 0.091 | 0.137 | 0.235 |
| `module:navigator` | 0.091 | 0.137 | 0.235 |
| `task:OPT-012` | 0.003 | 0.136 | 0.307 |
| `property:navigator.platform` | 0.095 | 0.108 | 0.231 |
| `recommendation:review_the_other_surface_for_value_descriptor_prototype_and_cross_property_consistency` | 0.131 | 0.067 | 0.269 |
| `task:OPT-207` | 0.002 | 0.057 | 0.303 |
| `property:webgl.aliased_point_size_range[1]` | 0.004 | 0.057 | 0.259 |
| `property:navigator.userAgent` | 0.016 | 0.056 | 0.269 |
| `task:OPT-001` | 0.006 | 0.051 | 0.310 |

## Clusters

Connected components: **45**; strongly connected groups: **2**.

| Component | Size |
|---|---:|
| component:001 | 2056 |
| component:002 | 7 |
| component:003 | 4 |
| component:004 | 3 |
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
- **Most Connected Module**: `Navigator`
- **Highest Risk Cluster**: `component:001`
- **Highest Roi Cluster**: `OPT-014`
- **Most Critical Dependency Chain**: `{'task_ids': ['OPT-001', 'OPT-009'], 'length': 2, 'estimated_gain': 0.793, 'estimated_effort': 11.0, 'estimated_risk': 163.2}`
- **Most Frequently Appearing Property**: `property:webgl.aliased_point_size_range[1]`

## Module Analysis

| Module | Properties | Internal density | External deps | Cross links |
|---|---:|---:|---:|---:|
| Chrome | 17 | 0.000 | 85 | 51 |
| Environment | 29 | 0.000 | 70 | 0 |
| Fonts | 26 | 0.000 | 104 | 52 |
| Navigator | 194 | 0.002 | 908 | 2 |
| Other | 445 | 0.000 | 2051 | 0 |
| Performance | 11 | 0.000 | 44 | 21 |
| Permissions | 7 | 0.000 | 28 | 14 |
| Screen | 9 | 0.194 | 163 | 25 |
| Speech | 68 | 0.000 | 269 | 135 |
| Storage | 10 | 0.000 | 50 | 0 |
| WebGL | 53 | 0.000 | 316 | 208 |
| Window | 11 | 0.227 | 126 | 18 |

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
- Learning candidates: 1
- Optimization candidates: 25
- Uncertain relationships: 0

## Validation

- Valid: **True**
- Deterministic ordering: **True**
- Artifact completeness: **True**

## Final Conclusion

The graph is a deterministic, read-only evidence map that can be reused by future planning experiments.

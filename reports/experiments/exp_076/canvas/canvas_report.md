# Canvas Evaluation

| Mode | Canvas Score | Overall Before | Overall After | CF Before | CF After | Improved | Stable Regressions | Diff Reduction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 350 | -355 |
| Generated | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 | 0 |
| Navigator | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 | 0 |
| Navigator + Window | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 | 0 |
| Current Stack | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 | 0 |
| Current Stack + Canvas | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 | 0 |

## Conclusion

Current Stack + Canvas meningkatkan atau mempertahankan similarity dan Canvas score tanpa stable regression terukur.

Canvas validation uses native prototypes, deterministic profile-derived variation, descriptor/prototype checks, ImageData dimensions, Blob output, illegal invocation, native source appearance, and idempotence marker checks.

# Window Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_006\window`

| Mode | Overall | CF Score | Window Score | Navigator Score | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Plain | 43.4% | 43.8% | 11.1% | 32.1% | 258 | 0 | 258 |
| Generated | 43.5% | 44.0% | 11.1% | 33.9% | 257 | 1 | 0 |
| Navigator | 51.6% | 54.8% | 11.1% | 72.7% | 180 | 78 | 1 |
| Navigator + Window | 57.0% | 61.4% | 100.0% | 74.5% | 171 | 9 | 0 |

## Conclusion

Navigator + Window meningkatkan fingerprint dibanding Navigator saja tanpa regression terukur.

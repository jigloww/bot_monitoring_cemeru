# Screen Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_007\screen`

| Mode | Overall | CF Score | Screen Score | Window Score | Navigator Score | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 43.5% | 44.0% | 50.0% | 11.1% | 33.9% | 257 | 0 | 256 |
| Generated | 43.5% | 44.0% | 50.0% | 11.1% | 33.9% | 257 | 0 | 0 |
| Navigator | 51.7% | 55.0% | 50.0% | 11.1% | 74.5% | 179 | 78 | 0 |
| Navigator + Window | 57.0% | 61.4% | 50.0% | 100.0% | 74.5% | 171 | 8 | 0 |
| Navigator + Window + Screen | 59.8% | 63.8% | 100.0% | 100.0% | 72.7% | 168 | 4 | 0 |

Environmental note: network-sampled Navigator connection values are listed separately and excluded from module regression counts.

## Conclusion

Navigator + Window + Screen meningkatkan fingerprint dibanding Navigator + Window tanpa regression terukur.

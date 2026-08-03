# Experiment 012 - Performance Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_012\performance`

| Mode | Overall | CF Score | Performance Score | Total Diff | Improved | Regression |
|---|---:|---:|---:|---:|---:|---:|
| Plain | 43.3% | 43.7% | 10.0% | 259 | 0 | 257 |
| Generated | 43.4% | 43.8% | 10.0% | 258 | 1 | 0 |
| Navigator | 51.6% | 54.8% | 10.0% | 180 | 78 | 0 |
| Navigator + Window | 56.9% | 61.2% | 10.0% | 172 | 8 | 0 |
| Navigator + Window + Screen | 59.7% | 63.6% | 10.0% | 169 | 4 | 0 |
| Navigator + Window + Screen + Chrome | 65.7% | 74.1% | 10.0% | 153 | 16 | 0 |
| Navigator + Window + Screen + Chrome + Permissions | 66.4% | 74.6% | 10.0% | 153 | 1 | 0 |
| Navigator + Window + Screen + Chrome + Permissions + Fonts | 66.5% | 74.8% | 10.0% | 152 | 1 | 0 |
| Navigator + Window + Screen + Chrome + Permissions + Fonts + Speech | 72.3% | 78.7% | 10.0% | 85 | 68 | 0 |
| Navigator + Window + Screen + Chrome + Permissions + Fonts + Speech + Performance | 77.0% | 81.6% | 90.0% | 77 | 8 | 0 |

Delta vs Fonts + Speech: Overall +4.7 pp, CF +2.9 pp.

Environmental note: network-sampled Navigator connection values are excluded from stable regression counts.

## Conclusion

Performance Module meningkatkan fingerprint secara terukur tanpa stable regression.

# Experiment 011 - Speech Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_011\speech`

| Mode | Overall | CF Score | Speech Score | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|
| Plain | 43.3% | 43.7% | 0.0% | 259 | 0 | 257 |
| Generated | 43.3% | 43.7% | 0.0% | 259 | 0 | 0 |
| Navigator | 51.6% | 54.8% | 0.0% | 180 | 79 | 0 |
| Navigator + Window | 56.9% | 61.2% | 0.0% | 172 | 8 | 0 |
| Navigator + Window + Screen | 59.8% | 63.8% | 0.0% | 168 | 4 | 0 |
| Navigator + Window + Screen + Chrome | 65.6% | 73.9% | 0.0% | 154 | 15 | 0 |
| Chrome Stack | 65.7% | 74.1% | 0.0% | 153 | 1 | 0 |
| Chrome + Permissions | 66.5% | 74.8% | 0.0% | 152 | 1 | 0 |
| Permissions + Fonts | 66.5% | 74.8% | 0.0% | 152 | 0 | 0 |
| Fonts + Speech | 72.3% | 78.7% | 100.0% | 85 | 68 | 0 |

Environmental note: network-sampled Navigator connection values are excluded from stable regression counts.

## Conclusion

Speech Module meningkatkan fingerprint secara terukur tanpa stable regression.

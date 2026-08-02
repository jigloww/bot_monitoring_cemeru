# Experiment 009 — Permissions Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_009\permissions`

| Mode | Overall | CF Score | Permissions | Chrome | Navigator | Window | Screen | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 43.4% | 43.8% | 85.7% | 0.0% | 32.1% | 11.1% | 50.0% | 258 | 0 | 256 |
| Generated | 43.5% | 44.0% | 85.7% | 0.0% | 33.9% | 11.1% | 50.0% | 257 | 1 | 0 |
| Navigator | 51.7% | 55.0% | 85.7% | 0.0% | 74.5% | 11.1% | 50.0% | 179 | 78 | 0 |
| Navigator + Window | 56.9% | 61.2% | 85.7% | 0.0% | 72.7% | 100.0% | 50.0% | 172 | 8 | 0 |
| Navigator + Window + Screen | 59.8% | 63.8% | 85.7% | 0.0% | 72.7% | 100.0% | 100.0% | 168 | 4 | 0 |
| Navigator + Window + Screen + Chrome | 65.8% | 74.3% | 85.7% | 100.0% | 74.5% | 100.0% | 100.0% | 152 | 16 | 0 |
| Navigator + Window + Screen + Chrome + Permissions | 66.6% | 74.9% | 100.0% | 100.0% | 74.5% | 100.0% | 100.0% | 151 | 1 | 0 |

Environmental note: network-sampled Navigator connection values are listed separately and excluded from stable regression counts.

## Conclusion

Permissions Module meningkatkan fingerprint dibanding Chrome stack tanpa stable regression.

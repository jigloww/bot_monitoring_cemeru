# Experiment 008 — Chrome Runtime Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_008\chrome`

| Mode | Overall | CF Score | Chrome | Navigator | Window | Screen | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 43.5% | 44.0% | 0.0% | 33.9% | 11.1% | 50.0% | 257 | 0 | 256 |
| Generated | 43.4% | 43.8% | 0.0% | 32.1% | 11.1% | 50.0% | 258 | 0 | 0 |
| Navigator | 51.7% | 55.0% | 0.0% | 74.5% | 11.1% | 50.0% | 179 | 79 | 0 |
| Navigator + Window | 57.0% | 61.4% | 0.0% | 74.5% | 100.0% | 50.0% | 171 | 8 | 0 |
| Navigator + Window + Screen | 59.8% | 63.8% | 0.0% | 72.7% | 100.0% | 100.0% | 168 | 4 | 0 |
| Navigator + Window + Screen + Chrome | 65.8% | 74.3% | 100.0% | 74.5% | 100.0% | 100.0% | 152 | 16 | 0 |

Environmental note: network-sampled Navigator connection values are listed separately and excluded from stable regression counts.

## Conclusion

Chrome Runtime meningkatkan fingerprint dibanding Navigator + Window + Screen tanpa stable regression.

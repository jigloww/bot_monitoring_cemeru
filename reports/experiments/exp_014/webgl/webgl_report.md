# Experiment 014 - WebGL Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_014\webgl`

| Mode | Overall | CF Score | WebGL Score | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|
| Plain | 43.4% | 43.8% | 62.5% | 258 | 0 | 257 |
| Generated | 43.3% | 43.7% | 62.5% | 259 | 0 | 0 |
| Navigator + Window + Screen + Chrome + Permissions + Fonts + Speech + Performance | 77.1% | 81.8% | 62.5% | 76 | 183 | 0 |
| Previous Stack | 77.0% | 81.6% | 62.5% | 77 | 0 | 0 |
| Previous Stack + WebGL | 78.9% | 84.8% | 93.8% | 72 | 5 | 0 |

Delta vs Previous Stack: Overall +1.9 pp, CF +3.2 pp, WebGL +31.3 pp.

Environmental note: network-sampled Navigator connection values are excluded from stable regression counts.

## Conclusion

WebGL Module meningkatkan WebGL dan similarity keseluruhan tanpa stable regression.

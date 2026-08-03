# Experiment 010 - Fonts Evaluation

Output: `D:\bot_monitoring_cemeru\reports\experiments\exp_010\fonts`

| Mode | Overall | CF Score | Fonts | Permissions | Chrome | Navigator | Window | Screen | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Plain | 43.4% | 43.8% | 100.0% | 85.7% | 0.0% | 32.1% | 11.1% | 50.0% | 258 | 0 | 256 |
| Generated | 43.5% | 44.0% | 100.0% | 85.7% | 0.0% | 33.9% | 11.1% | 50.0% | 257 | 1 | 0 |
| Navigator | 51.7% | 55.0% | 100.0% | 85.7% | 0.0% | 74.5% | 11.1% | 50.0% | 179 | 78 | 0 |
| Navigator + Window | 56.9% | 61.2% | 100.0% | 85.7% | 0.0% | 72.7% | 100.0% | 50.0% | 172 | 8 | 0 |
| Navigator + Window + Screen | 59.8% | 63.8% | 100.0% | 85.7% | 0.0% | 72.7% | 100.0% | 100.0% | 168 | 4 | 0 |
| Navigator + Window + Screen + Chrome | 65.7% | 74.1% | 100.0% | 85.7% | 100.0% | 72.7% | 100.0% | 100.0% | 153 | 15 | 0 |
| Navigator + Window + Screen + Chrome + Permissions | 66.5% | 74.8% | 100.0% | 100.0% | 100.0% | 72.7% | 100.0% | 100.0% | 152 | 1 | 0 |
| Navigator + Window + Screen + Chrome + Permissions + Fonts | 66.6% | 74.9% | 100.0% | 100.0% | 100.0% | 74.5% | 100.0% | 100.0% | 151 | 1 | 0 |

Environmental note: network-sampled Navigator connection values are excluded from stable regression counts.

## Conclusion

Fonts category sudah 100% pada native browser; module mempertahankan kecocokan tanpa stable regression. Perubahan kecil pada stack bersifat lingkungan, bukan kontribusi Fonts yang terukur.

# Experiment 001 — Navigator Evaluation

- Baseline: `reports\fingerprint\fingerprint_real.json`
- URL: `about:blank`
- Headless: `True`

| Mode | Overall | CF Score | Navigator % | Total Diff | Improved | Regressed |
|---|---:|---:|---:|---:|---:|---:|
| Plain | 43.5% | 44.0% | 33.9% | 257 | 0 | 257 |
| Generated | 43.4% | 43.8% | 32.1% | 258 | 0 | 1 |
| Navigator | 51.6% | 54.8% | 72.7% | 180 | 78 | 0 |

## Unchanged Keys

| Mode | Unchanged | Transition from |
|---|---:|---|
| Plain | 107 | baseline |
| Generated | 359 | plain |
| Navigator | 270 | generated |

## Conclusion

Navigator module lebih baik dibanding generated patch (indikator lebih baik: 4, lebih buruk: 0).

The conclusion votes on overall similarity, weighted CF score, Navigator category score, and total diff count.

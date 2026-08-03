# Experiment 026 — Prediction Validator

Read-only validation of Optimization Planner predictions against subsequent scored artifacts. No browser or network request was used.

## Executive Summary

Result: **PARTIAL**
Predictions evaluated: **0**
Prediction accuracy: **Insufficient Data**
Planner confidence: **Insufficient Data**

## Prediction Accuracy

| Metric | Value |
|---|---:|
| prediction_accuracy_pct | Insufficient Data |
| mae | Insufficient Data |
| rmse | Insufficient Data |
| mbe | Insufficient Data |
| evaluated_count | 0 |

## Prediction Classification

| Prediction | Sprint | Predicted Gain | Actual Gain | Classification |
|---|---|---:|---:|---|
| sprint_1 | Sprint 1 | 3.5685 | N/A | Insufficient Data |
| sprint_2 | Sprint 2 | 3.2386 | N/A | Insufficient Data |
| sprint_3 | Sprint 3 | 87.2574 | N/A | Insufficient Data |
| sprint_4 | Sprint 4 | 2.2595 | N/A | Insufficient Data |

## Property Accuracy

Property predictions: **471**; all are classified against property-level observations only.

## Difficulty Validation

Classification: **Insufficient Data**

## Confidence Analysis

{
  "classification": "Insufficient Data",
  "coverage_pct": 0.0,
  "evaluated_predictions": 0,
  "insufficient_predictions": 4,
  "difficulty_validation": {
    "classification": "Insufficient Data",
    "evaluated_properties": 0,
    "reason": "No post-planner property-level compare artifact is available."
  },
  "basis": "Coverage and error metrics from subsequent immutable experiment artifacts."
}

## Recommendations

- **HIGH — perlu data tambahan**: Run at least one scored experiment after the planner before calibrating prediction accuracy, penalty, or confidence. (No post-planner actual observation available.)
- **MEDIUM — perlu data tambahan**: Do not recalibrate difficulty from score changes alone; collect property-level compare results. (No property-level post-planner observations.)

## Validation

Validation details are stored in `validation.json`; source artifacts remain unchanged.

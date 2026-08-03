# Experiment 035 — Real MediaDevices Collector

## Summary

- Result: **SUCCESS**
- URL: **https://example.com**
- Browser started through Browser Platform: **True**
- MediaDevices available: **True**
- Device count: **3**

## Device Counts

| Kind | Count |
|---|---:|
| audioinput | 1 |
| audiooutput | 1 |
| default | 0 |
| videoinput | 1 |

## Permissions

Permission queries are observational only. No camera, microphone, display, or recording API was invoked.

## Validation

| Check | Status |
|---|---|
| Python Compile | PASS |
| Json Validation | PASS |
| Artifact Completeness | PASS |
| Deterministic Ordering | PASS |
| Serialization | PASS |
| Read Only Verification | PASS |
| No Stealth Injection | PASS |
| Browser Platform Entrypoint | PASS |
| Permission Request Absent | PASS |
| Valid | PASS |

## Read-only Boundary

The collector does not install stealth, request permissions, call getUserMedia(), call getDisplayMedia(), record audio/video, intercept network traffic, or modify browser prototypes.

"""Before/after fingerprint and generated-patch outcome metrics."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from tools.compare_fingerprint import vals_equal


@dataclass(frozen=True)
class ExperimentMetrics:
    """Metrics calculated against one immutable reference fingerprint."""

    patch_target_count: int
    patches_successful: int
    patches_failed: int
    patches_no_effect: int
    diff_count_before: int
    diff_count_after: int
    diff_reduction: int
    diff_reduction_pct: float
    overall_improvement: float
    overall_improvement_pct: float
    cf_risk_improvement: float
    improved_keys: list[str] = field(default_factory=list)
    regressed_keys: list[str] = field(default_factory=list)
    unchanged_keys: list[str] = field(default_factory=list)
    changed_remaining_keys: list[str] = field(default_factory=list)
    successful_patch_keys: list[str] = field(default_factory=list)
    failed_patch_keys: list[str] = field(default_factory=list)
    no_effect_patch_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["definitions"] = {
            "patches_successful": "Generated target differed before and matches the baseline after.",
            "patches_failed": "Generated target changed but still differs from the baseline, regressed, or cannot be validated.",
            "patches_no_effect": "Generated target observation did not change, including targets already matching before.",
            "unchanged_keys": "Before and after observations are equal, whether matching or differing from baseline.",
        }
        return data


def _matches(reference: dict[str, Any], candidate: dict[str, Any], key: str) -> bool:
    if (key in reference) != (key in candidate):
        return False
    if key not in reference:
        return True
    return vals_equal(reference[key], candidate[key])


def _same_observation(before: dict[str, Any], after: dict[str, Any], key: str) -> bool:
    if (key in before) != (key in after):
        return False
    if key not in before:
        return True
    return vals_equal(before[key], after[key])


def calculate_metrics(
    reference: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    score_before: dict[str, Any],
    score_after: dict[str, Any],
    patch_keys: Iterable[str] = (),
) -> ExperimentMetrics:
    """Calculate global changes and observed outcomes for generated patch keys."""
    all_keys = sorted(set(reference) | set(before) | set(after))
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    changed_remaining: list[str] = []

    diff_before = sum(
        not _matches(reference, before, key)
        for key in set(reference) | set(before)
    )
    diff_after = sum(
        not _matches(reference, after, key)
        for key in set(reference) | set(after)
    )
    for key in all_keys:
        was_match = _matches(reference, before, key)
        is_match = _matches(reference, after, key)

        if not was_match and is_match:
            improved.append(key)
        elif was_match and not is_match:
            regressed.append(key)
        elif _same_observation(before, after, key):
            unchanged.append(key)
        elif not was_match and not is_match:
            changed_remaining.append(key)

    successful_patches: list[str] = []
    failed_patches: list[str] = []
    no_effect_patches: list[str] = []
    unique_patch_keys = sorted(set(patch_keys))
    for key in unique_patch_keys:
        was_match = _matches(reference, before, key)
        is_match = _matches(reference, after, key)
        same = _same_observation(before, after, key)
        if not was_match and is_match:
            successful_patches.append(key)
        elif same:
            no_effect_patches.append(key)
        else:
            failed_patches.append(key)

    reduction = diff_before - diff_after
    reduction_pct = (reduction / diff_before * 100.0) if diff_before else 0.0
    overall_before = float(score_before.get("overall_score", 0.0))
    overall_after = float(score_after.get("overall_score", 0.0))
    overall_delta = overall_after - overall_before
    overall_pct = (overall_delta / overall_before * 100.0) if overall_before else 0.0
    cf_delta = float(score_after.get("cf_risk_score", 0.0)) - float(
        score_before.get("cf_risk_score", 0.0)
    )

    return ExperimentMetrics(
        patch_target_count=len(unique_patch_keys),
        patches_successful=len(successful_patches),
        patches_failed=len(failed_patches),
        patches_no_effect=len(no_effect_patches),
        diff_count_before=diff_before,
        diff_count_after=diff_after,
        diff_reduction=reduction,
        diff_reduction_pct=round(reduction_pct, 2),
        overall_improvement=round(overall_delta, 2),
        overall_improvement_pct=round(overall_pct, 2),
        cf_risk_improvement=round(cf_delta, 2),
        improved_keys=improved,
        regressed_keys=regressed,
        unchanged_keys=unchanged,
        changed_remaining_keys=changed_remaining,
        successful_patch_keys=successful_patches,
        failed_patch_keys=failed_patches,
        no_effect_patch_keys=no_effect_patches,
    )

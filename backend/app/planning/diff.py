"""Plan diff (DATA_MODEL PlanDiff). Assignments are matched by id (`S-<mission>-<n>`)."""

from __future__ import annotations

from app.models.plans import FieldChange, Plan, PlanDiff

COMPARED = ("aircraft_id", "takeoff_min", "land_min", "loadout_id", "crew_ids", "base_from")


def diff_plans(old: Plan, new: Plan) -> PlanDiff:
    a = {x.id: x for x in old.assignments}
    b = {x.id: x for x in new.assignments}
    changed: list[FieldChange] = []
    for aid in sorted(a.keys() & b.keys()):
        for f in COMPARED:
            if getattr(a[aid], f) != getattr(b[aid], f):
                changed.append(FieldChange.model_validate(
                    {"assignment_id": aid, "field": f, "from": getattr(a[aid], f),
                     "to": getattr(b[aid], f)}
                ))
    added, removed = sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys())
    return PlanDiff(
        added=added, removed=removed, changed=changed,
        n_changes=len(added) + len(removed) + len({c.assignment_id for c in changed}),
        coverage_delta=round(
            new.kpis.priority_weighted_coverage - old.kpis.priority_weighted_coverage, 4),
        risk_delta=round(new.kpis.mean_risk - old.kpis.mean_risk, 4),
    )

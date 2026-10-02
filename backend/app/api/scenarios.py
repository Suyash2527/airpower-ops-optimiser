"""Scenario endpoints (API_SPEC "Scenarios & state"). Every response carries `data_label`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, ValidationError
from sqlmodel import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.models import store
from app.models.entities import Model
from app.models.scenario import GeneratorParams, ScenarioFile
from app.sim.generate import generate_scenario
from app.sim.scenario_io import load_scenario

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

DataLabel = Literal["synthetic", "open", "mixed"]


class ScenarioSummary(BaseModel):
    scenario_id: str
    name: str
    seed: int
    t0: AwareDatetime
    horizon_min: int
    season_preset: str
    region_mix: dict[str, int]
    counts: dict[str, int]
    data_label: DataLabel


class ScenarioList(BaseModel):
    scenarios: list[ScenarioSummary]
    data_label: DataLabel = "synthetic"


class Snapshot(ScenarioFile):
    """Fused state. Phase 1 returns the stored records with their provenance; staleness and
    conflict handling arrive with the fusion layer (Phase 2)."""

    scenario_id: str
    data_label: DataLabel


class LoadRequest(Model):
    path: str


def _summary(sid: str, scenario: ScenarioFile) -> ScenarioSummary:
    meta = scenario.scenario
    return ScenarioSummary(
        scenario_id=sid, name=meta.name, seed=meta.seed, t0=meta.t0, horizon_min=meta.horizon_min,
        season_preset=meta.season_preset.value, region_mix=meta.region_mix,
        counts=scenario.counts(), data_label=meta.data_label,
    )


@router.post("/generate", response_model=ScenarioSummary)
def generate(params: GeneratorParams, session: Session = Depends(get_session)) -> ScenarioSummary:
    try:
        scenario = generate_scenario(params)
    except ValueError as exc:  # e.g. not enough eligible base sites for the chosen regions
        raise ApiError(422, "invalid_parameters", str(exc)) from exc
    return _summary(store.save_scenario_rows(session, scenario), scenario)


@router.post("/load", response_model=ScenarioSummary)
def load(
    body: LoadRequest, request: Request, session: Session = Depends(get_session)
) -> ScenarioSummary:
    root = Path(request.app.state.settings.scenario_dir).resolve()
    candidate = Path(body.path)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not path.is_relative_to(root) or path.suffix != ".json":
        raise ApiError(400, "invalid_path", "path must be a .json file inside the scenario folder")
    if not path.is_file():
        raise ApiError(404, "not_found", f"scenario file not found: {body.path}")
    try:
        scenario = load_scenario(path)
    except ValidationError as exc:
        msg = f"not a valid scenario file: {exc.error_count()} errors"
        raise ApiError(422, "invalid_scenario", msg) from exc
    return _summary(store.save_scenario_rows(session, scenario), scenario)


@router.get("", response_model=ScenarioList)
def list_all(session: Session = Depends(get_session)) -> ScenarioList:
    rows = store.list_scenarios(session)
    return ScenarioList(
        scenarios=[
            ScenarioSummary(
                scenario_id=r.id, name=r.name, seed=r.seed, t0=r.meta["t0"],
                horizon_min=r.horizon_min, season_preset=r.meta["season_preset"],
                region_mix=r.meta["region_mix"], counts=r.counts, data_label=r.data_label,  # type: ignore[arg-type]
            )
            for r in rows
        ]
    )


@router.get("/{scenario_id}/snapshot", response_model=Snapshot)
def snapshot(scenario_id: str, session: Session = Depends(get_session)) -> Snapshot:
    scenario = store.load_scenario_rows(session, scenario_id)
    if scenario is None:
        raise ApiError(404, "not_found", f"unknown scenario: {scenario_id}")
    return Snapshot(
        **{name: getattr(scenario, name) for name in ScenarioFile.model_fields},
        scenario_id=scenario_id, data_label=scenario.scenario.data_label,
    )

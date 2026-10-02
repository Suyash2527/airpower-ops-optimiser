from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.scenario import GeneratorParams, ScenarioFile
from app.sim.generate import generate_scenario


@pytest.fixture(scope="session")
def scenario42() -> ScenarioFile:
    return generate_scenario(GeneratorParams(seed=42))


@pytest.fixture
def scenario_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(scenario_dir: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_url="sqlite://", scenario_dir=scenario_dir, solver_time_limit_s=1.0
    )
    with TestClient(create_app(settings)) as c:
        yield c

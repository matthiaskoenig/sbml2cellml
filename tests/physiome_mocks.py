"""Shared Physiome mocks for the runner and CLI tests.

`model_path` is monkeypatched to serve local CellML files instead of cloning
a workspace: `EXPOSURE_MULTI` resolves to the multi component model written
into the temporary directory, `EXPOSURE_BROKEN` to a file which libcellml
cannot analyse and `EXPOSURE_MISSING` raises `PhysiomeError`.
"""

from pathlib import Path

import pytest

from sbml2cellml.cellml import write_model
from sbml2cellml.physiome import runner
from sbml2cellml.physiome.models import PHYSIOME_URL, Exposure, PhysiomeError
from tests.cellml_models import multi_component_model, underconstrained_model

#: exposure of the multi component model
EXPOSURE_MULTI = Exposure(
    id="multi",
    title="Multi component model",
    workspace=f"{PHYSIOME_URL}/workspace/multi",
    commit="a" * 40,
    path="multi.cellml",
)
#: exposure of a model libcellml cannot analyse
EXPOSURE_BROKEN = Exposure(
    id="broken",
    title="Underconstrained model",
    workspace=f"{PHYSIOME_URL}/workspace/broken",
    commit="b" * 40,
    path="broken.cellml",
)
#: exposure whose workspace cannot be cloned
EXPOSURE_MISSING = Exposure(
    id="missing",
    title="Missing workspace",
    workspace=f"{PHYSIOME_URL}/workspace/missing",
    commit="c" * 40,
    path="missing.cellml",
)


def write_models(directory: Path) -> dict[str, Path]:
    """Write the CellML files of the mocked exposures.

    Args:
        directory: directory to write them into.

    Returns:
        The path of the file by exposure id.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        EXPOSURE_MULTI.id: directory / EXPOSURE_MULTI.path,
        EXPOSURE_BROKEN.id: directory / EXPOSURE_BROKEN.path,
    }
    write_model(multi_component_model(), paths[EXPOSURE_MULTI.id])
    write_model(underconstrained_model(), paths[EXPOSURE_BROKEN.id])
    return paths


def mock_workspaces(
    monkeypatch: pytest.MonkeyPatch, directory: Path
) -> dict[str, Path]:
    """Serve the CellML files of the mocked exposures from a directory.

    Args:
        monkeypatch: the fixture.
        directory: directory the files are written into.

    Returns:
        The path of the file by exposure id.
    """
    paths = write_models(directory)

    def fake_model_path(exposure: Exposure, cache: Path | None = None) -> Path:
        if exposure.id not in paths:
            raise PhysiomeError(f"Exposure {exposure.id} cannot be cloned")
        return paths[exposure.id]

    monkeypatch.setattr(runner, "model_path", fake_model_path)
    return paths

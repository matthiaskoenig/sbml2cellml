"""Tests of the access to the Physiome Model Repository."""

import json
import stat
import subprocess
from pathlib import Path

import pytest
import requests

from sbml2cellml.physiome import models
from sbml2cellml.physiome.models import (
    PHYSIOME_URL,
    Exposure,
    PhysiomeError,
    exposure,
    exposure_urls,
    model_path,
    physiome_cache,
    query_exposures,
    read_selection,
    remove_tree,
    workspace_dir,
    write_selection,
)
from sbml2cellml.testsuite.cases import CACHE_ENV

EXPOSURE = Exposure(
    id="5f",
    title="Winslow, Rice, Jafri, Marban, O'Rorke, 1999",
    workspace=f"{PHYSIOME_URL}/workspace/winslow_rice",
    commit="3ffc9e3c3f1e07e5b8a06d3f3a7d7f3d2b1c4a5e",
    path="winslow_rice_1999.cellml",
)


class FakeResponse:
    """Minimal stand-in for `requests.Response`."""

    def __init__(self, payload: object = None) -> None:
        self._payload = payload
        self.raises: Exception | None = None

    def raise_for_status(self) -> None:
        if self.raises is not None:
            raise self.raises

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _exposure_payload(
    commit: str = EXPOSURE.commit, cellml: bool = True
) -> dict[str, object]:
    links: list[dict[str, str]] = [
        {"prompt": "Workspace URL", "href": EXPOSURE.workspace},
    ]
    if cellml:
        links.append(
            {
                "prompt": "model.cellml",
                "href": f"{PHYSIOME_URL}/e/5f/{EXPOSURE.path}/view",
            }
        )
    return {
        "collection": {
            "items": [
                {
                    "data": [
                        {"name": "title", "value": "Winslow, Rice, Jafri, "},
                        {"name": "commit_id", "value": commit},
                    ]
                }
            ],
            "links": links,
        }
    }


def test_exposure_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "collection": {
            "links": [
                {"href": f"{PHYSIOME_URL}/e/5f"},
                {"href": f"{PHYSIOME_URL}/e/60"},
                {"href": f"{PHYSIOME_URL}/about"},
            ]
        }
    }
    monkeypatch.setattr(models.requests, "get", lambda *a, **k: FakeResponse(payload))
    assert exposure_urls() == [f"{PHYSIOME_URL}/e/5f", f"{PHYSIOME_URL}/e/60"]


def test_exposure_reads_title_commit_and_file(monkeypatch: pytest.MonkeyPatch) -> None:
    headers: list[object] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        headers.append(kwargs["headers"])
        return FakeResponse(_exposure_payload())

    monkeypatch.setattr(models.requests, "get", fake_get)
    found = exposure(f"{PHYSIOME_URL}/e/5f")
    assert found == Exposure(
        id="5f",
        title="Winslow, Rice, Jafri,",
        workspace=EXPOSURE.workspace,
        commit=EXPOSURE.commit,
        path=EXPOSURE.path,
    )
    assert headers == [{"Accept": models.JSON_ACCEPT}]


def test_exposure_without_cellml_file_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        models.requests,
        "get",
        lambda *a, **k: FakeResponse(_exposure_payload(cellml=False)),
    )
    assert exposure(f"{PHYSIOME_URL}/e/5f") is None


def test_exposure_without_commit_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        models.requests,
        "get",
        lambda *a, **k: FakeResponse(_exposure_payload(commit="")),
    )
    assert exposure(f"{PHYSIOME_URL}/e/5f") is None


def test_request_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(models.requests, "get", fake_get)
    with pytest.raises(PhysiomeError, match="no network"):
        exposure_urls()


def test_query_exposures_keeps_one_per_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [f"{PHYSIOME_URL}/e/{i}" for i in ("5f", "60", "61", "62")]
    found: dict[str, Exposure | PhysiomeError | None] = {
        urls[0]: EXPOSURE,
        # the same workspace, published again
        urls[1]: Exposure(**{**vars(EXPOSURE), "id": "60"}),
        urls[2]: None,
        urls[3]: PhysiomeError("broken"),
    }
    monkeypatch.setattr(models, "exposure_urls", lambda: urls)
    monkeypatch.setattr(
        models,
        "_exposure_or_none",
        lambda url: found[url],
    )
    assert query_exposures() == [EXPOSURE]


def test_query_exposures_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = [f"{PHYSIOME_URL}/e/{i}" for i in ("5f", "60")]
    second = Exposure(**{**vars(EXPOSURE), "id": "60", "workspace": "other"})
    monkeypatch.setattr(models, "exposure_urls", lambda: urls)
    monkeypatch.setattr(
        models,
        "_exposure_or_none",
        lambda url: EXPOSURE if url.endswith("5f") else second,
    )
    assert query_exposures(limit=1) == [EXPOSURE]


def test_selection_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    written = write_selection([EXPOSURE], path)
    assert written.models == (EXPOSURE,)
    assert json.loads(path.read_text(encoding="utf-8"))["source"] == PHYSIOME_URL
    read = read_selection(path)
    assert read.models == (EXPOSURE,)
    assert read.date == written.date


def test_read_selection_without_models_raises(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text('{"date": "2026-11-23", "models": []}', encoding="utf-8")
    with pytest.raises(PhysiomeError, match="holds no models"):
        read_selection(path)


def test_read_selection_of_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PhysiomeError, match="cannot be read"):
        read_selection(tmp_path / "missing.json")


def _workspace(path: Path) -> None:
    """Create a git repository with a CellML file and commit it."""
    path.mkdir(parents=True, exist_ok=True)
    (path / EXPOSURE.path).write_text("<model/>", encoding="utf-8")
    for arguments in (
        ["init", "--quiet", "--initial-branch", "main", "."],
        ["config", "user.email", "test@example.org"],
        ["config", "user.name", "Test"],
        ["add", EXPOSURE.path],
        ["commit", "--quiet", "-m", "model"],
    ):
        subprocess.run(["git", *arguments], cwd=path, check=True, capture_output=True)


def _head(path: Path) -> str:
    """The commit of the head of a repository."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_workspace_is_cloned_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote"
    _workspace(remote)
    exposure_of_remote = Exposure(
        **{**vars(EXPOSURE), "workspace": str(remote), "commit": _head(remote)}
    )
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "cache"))
    path = model_path(exposure_of_remote)
    assert path.read_text(encoding="utf-8") == "<model/>"
    assert path.parent == physiome_cache() / "5f"

    calls: list[list[str]] = []
    monkeypatch.setattr(models, "_git", lambda arguments, cwd: calls.append(arguments))
    assert workspace_dir(exposure_of_remote) == path.parent
    assert calls == []


def test_workspace_of_another_commit_is_cloned_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote"
    _workspace(remote)
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "cache"))
    first = Exposure(
        **{**vars(EXPOSURE), "workspace": str(remote), "commit": _head(remote)}
    )
    model_path(first)
    (remote / EXPOSURE.path).write_text("<model name='second'/>", encoding="utf-8")
    for arguments in (["add", EXPOSURE.path], ["commit", "--quiet", "-m", "second"]):
        subprocess.run(["git", *arguments], cwd=remote, check=True, capture_output=True)
    second = Exposure(**{**vars(first), "commit": _head(remote)})
    assert model_path(second).read_text(encoding="utf-8") == "<model name='second'/>"


def test_remove_tree_removes_a_read_only_file(tmp_path: Path) -> None:
    """git marks its objects read-only, which windows refuses to unlink."""
    root = tmp_path / "workspace"
    (root / "objects").mkdir(parents=True)
    read_only = root / "objects" / "ab12"
    read_only.write_text("object", encoding="utf-8")
    read_only.chmod(stat.S_IREAD)
    remove_tree(root)
    assert not root.exists()


def test_model_path_of_a_missing_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote"
    _workspace(remote)
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "cache"))
    missing = Exposure(
        **{
            **vars(EXPOSURE),
            "workspace": str(remote),
            "commit": _head(remote),
            "path": "other.cellml",
        }
    )
    with pytest.raises(PhysiomeError, match=r"has no file 'other\.cellml'"):
        model_path(missing)


def test_clone_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_ENV, str(tmp_path / "cache"))
    broken = Exposure(**{**vars(EXPOSURE), "workspace": str(tmp_path / "missing")})
    with pytest.raises(PhysiomeError, match="git fetch"):
        workspace_dir(broken)

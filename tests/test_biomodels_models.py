"""Tests of the BioModels access: search paging, info, download, selection."""

import json
from pathlib import Path

import pytest
import requests

from sbml2cellml.biomodels import models
from sbml2cellml.biomodels.models import (
    BIOMODELS_URL,
    SEARCH_QUERY,
    BioModelsError,
    ModelInfo,
    Selection,
    download_model,
    load_selection,
    model_info,
    packages,
    query_curated_ids,
    write_selection,
)
from sbml2cellml.testsuite.cases import CACHE_ENV
from tests.conftest import MODELS_DIR

LIVER_MODEL = MODELS_DIR / "glimepiride_liver.xml"
INFO = {
    "name": "Edelstein1996 - EPSP ACh event",
    "publicationId": "BIOMD0000000001",
    "format": {"version": "L2V4"},
    "files": {"main": [{"name": "BIOMD0000000001_url.xml"}]},
}


class FakeResponse:
    """Minimal stand-in for `requests.Response`."""

    def __init__(self, payload: object = None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content
        self.raises: Exception | None = None

    def raise_for_status(self) -> None:
        if self.raises is not None:
            raise self.raises

    def json(self) -> object:
        return self._payload

    def iter_content(self, chunk_size: int = 1 << 16) -> object:
        yield self.content

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _search_page(ids: list[str], matches: int) -> FakeResponse:
    return FakeResponse(
        {
            "matches": matches,
            "models": [{"id": i, "name": i, "format": "SBML"} for i in ids],
        }
    )


def test_query_curated_ids_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [f"BIOMD{i:010d}" for i in range(1, 13)]
    monkeypatch.setattr(models, "PAGE_SIZE", 5)
    offsets: list[int] = []

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        assert url == f"{BIOMODELS_URL}/search"
        assert params is not None
        assert params["query"] == SEARCH_QUERY
        assert params["format"] == "json"
        offset = int(params["offset"])
        offsets.append(offset)
        page = ids[offset : offset + 5]
        return _search_page(page, matches=12)

    monkeypatch.setattr(models.requests, "get", fake_get)
    result = query_curated_ids()
    assert result == sorted(ids)
    assert offsets == [0, 5, 10]


def test_model_info_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_ENV, str(tmp_path))
    calls: list[str] = []

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        calls.append(url)
        assert url == f"{BIOMODELS_URL}/BIOMD0000000001"
        assert params == {"format": "json"}
        return FakeResponse(INFO)

    monkeypatch.setattr(models.requests, "get", fake_get)
    info = model_info("BIOMD0000000001")
    assert info == ModelInfo(
        "BIOMD0000000001",
        "Edelstein1996 - EPSP ACh event",
        "BIOMD0000000001",
        "L2V4",
        "BIOMD0000000001_url.xml",
    )
    info_path = tmp_path / "biomodels" / "BIOMD0000000001" / "info.json"
    assert info_path.is_file()
    assert len(calls) == 1
    info_again = model_info("BIOMD0000000001")
    assert info_again == info
    assert len(calls) == 1


def test_download_model_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CACHE_ENV, str(tmp_path))
    content = LIVER_MODEL.read_bytes()
    calls: list[str] = []

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        calls.append(url)
        if url.startswith(f"{BIOMODELS_URL}/model/download/"):
            assert url == f"{BIOMODELS_URL}/model/download/BIOMD0000000001"
            assert params == {"filename": "BIOMD0000000001_url.xml"}
            assert stream is True
            return FakeResponse(content=content)
        return FakeResponse(INFO)

    monkeypatch.setattr(models.requests, "get", fake_get)
    path = download_model("BIOMD0000000001")
    assert (
        path == tmp_path / "biomodels" / "BIOMD0000000001" / "BIOMD0000000001_url.xml"
    )
    assert path.read_bytes() == content
    assert len(calls) == 2
    path_again = download_model("BIOMD0000000001")
    assert path_again == path
    assert len(calls) == 2


def test_download_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_ENV, str(tmp_path))

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> FakeResponse:
        if url.startswith(f"{BIOMODELS_URL}/model/download/"):
            response = FakeResponse()
            response.raises = requests.HTTPError("500 Server Error")
            return response
        return FakeResponse(INFO)

    monkeypatch.setattr(models.requests, "get", fake_get)
    with pytest.raises(BioModelsError, match="BIOMD0000000001"):
        download_model("BIOMD0000000001")


def test_selection_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    written = write_selection(path, ["BIOMD0000000002", "BIOMD0000000001"])
    assert written.models == ("BIOMD0000000001", "BIOMD0000000002")
    assert written.query == SEARCH_QUERY
    assert len(written.date) == 10 and written.date[4] == "-" and written.date[7] == "-"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["models"] == ["BIOMD0000000001", "BIOMD0000000002"]
    loaded = load_selection(path)
    assert loaded == written
    assert isinstance(loaded, Selection)


def test_packages(tmp_path: Path) -> None:
    root = tmp_path / "packages.xml"
    root.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
        'xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1" '
        'xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/version2" '
        'level="3" version="1"><model id="m"/></sbml>\n',
        encoding="utf-8",
    )
    assert packages(root) == ("comp", "fbc")
    # a model with no package namespace declares none
    plain = tmp_path / "plain.xml"
    plain.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" '
        'level="3" version="1"><model id="m"/></sbml>\n',
        encoding="utf-8",
    )
    assert packages(plain) == ()

"""Access to the BioModels database: search, model info, download, selection.

The curated model set is queried and downloaded through the BioModels REST
API (`https://www.biomodels.org`, `www.ebi.ac.uk/biomodels` rejects the
quoted search query used here). Model info and the downloaded SBML are
cached on disk under `biomodels_cache()` so a rerun of the check never
re-fetches a model it already has.
"""

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from sbml2cellml.testsuite.cases import cache_dir

logger = logging.getLogger(__name__)

#: root of the BioModels REST API
BIOMODELS_URL = "https://www.biomodels.org"
#: search query selecting the manually curated SBML models
SEARCH_QUERY = 'curationstatus:"Manually curated" AND modelformat:"SBML"'
#: number of models requested per search page
PAGE_SIZE = 100
#: timeout (seconds) of every BioModels request
TIMEOUT = 60.0
#: namespace declarations of an SBML package, e.g. `xmlns:comp="http://www.
#: sbml.org/sbml/level3/version1/comp/version1"`; group 2 is the package name
_XMLNS = re.compile(
    r'xmlns:(\w+)="http://www\.sbml\.org/sbml/level3/version\d+/(\w+)/version\d+"'
)
#: bytes read from the start of an SBML file to find its package namespaces
_XMLNS_HEAD = 8192


class BioModelsError(RuntimeError):
    """A BioModels request failed or returned an unexpected response."""


@dataclass(frozen=True)
class ModelInfo:
    """Metadata of one BioModels model, from `/{id}?format=json`."""

    id: str
    name: str
    publication_id: str
    format_version: str
    main_file: str


@dataclass(frozen=True)
class Selection:
    """A snapshot of the curated model ids, e.g. `biomodels/models.json`."""

    date: str
    query: str
    models: tuple[str, ...]


def biomodels_cache(cache: Path | None = None) -> Path:
    """Cache directory of the BioModels info and downloads.

    Args:
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.

    Returns:
        `<cache>/biomodels`.
    """
    return (cache or cache_dir()) / "biomodels"


def _get_json(url: str, params: dict[str, str | int] | None = None) -> dict:
    """`GET` a BioModels endpoint and parse its JSON body.

    Args:
        url: endpoint to request.
        params: query parameters.

    Returns:
        The parsed JSON body.

    Raises:
        BioModelsError: if the request fails or the status is not ok.
    """
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as err:
        raise BioModelsError(f"Request to {url} failed: {err}") from err


def query_curated_ids() -> list[str]:
    """Ids of every manually curated SBML model, paged through the search.

    Returns:
        The model ids, sorted and without duplicates.

    Raises:
        BioModelsError: if a search page cannot be fetched.
    """
    offset = 0
    ids: list[str] = []
    matches: int | None = None
    while matches is None or offset < matches:
        data = _get_json(
            f"{BIOMODELS_URL}/search",
            {
                "query": SEARCH_QUERY,
                "numResults": PAGE_SIZE,
                "offset": offset,
                "format": "json",
            },
        )
        matches = int(data["matches"])
        ids.extend(model["id"] for model in data["models"])
        offset += PAGE_SIZE
    logger.info("%d curated models found on BioModels", len(set(ids)))
    return sorted(set(ids))


def model_info(model_id: str, cache: Path | None = None) -> ModelInfo:
    """Metadata of a model, cached as `<cache>/biomodels/<id>/info.json`.

    Args:
        model_id: BioModels id, e.g. `BIOMD0000000001`.
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.

    Returns:
        The model metadata.

    Raises:
        BioModelsError: if the request fails or the response has no main
            SBML file.
    """
    root = biomodels_cache(cache) / model_id
    info_path = root / "info.json"
    if info_path.is_file():
        data = json.loads(info_path.read_text(encoding="utf-8"))
        return ModelInfo(**data)
    data = _get_json(f"{BIOMODELS_URL}/{model_id}", {"format": "json"})
    main_files = data.get("files", {}).get("main") or []
    if not main_files:
        raise BioModelsError(f"{model_id}: no main SBML file in the BioModels response")
    info = ModelInfo(
        id=model_id,
        name=data["name"],
        publication_id=data.get("publicationId", ""),
        format_version=data.get("format", {}).get("version", ""),
        main_file=main_files[0]["name"],
    )
    root.mkdir(parents=True, exist_ok=True)
    info_path.write_text(
        json.dumps(dataclasses.asdict(info), indent=1), encoding="utf-8"
    )
    logger.info("Fetched BioModels info for %s: %s", model_id, info.name)
    return info


def download_model(model_id: str, cache: Path | None = None) -> Path:
    """Download the main SBML file of a model, cached on disk.

    Args:
        model_id: BioModels id, e.g. `BIOMD0000000001`.
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.

    Returns:
        Path of the cached SBML file.

    Raises:
        BioModelsError: if the info or download request fails.
    """
    info = model_info(model_id, cache)
    root = biomodels_cache(cache) / model_id
    path = root / info.main_file
    if path.is_file():
        return path
    root.mkdir(parents=True, exist_ok=True)
    url = f"{BIOMODELS_URL}/model/download/{model_id}"
    tmp_path = path.with_name(path.name + ".part")
    logger.info("Downloading %s from %s", model_id, url)
    try:
        with requests.get(
            url, params={"filename": info.main_file}, stream=True, timeout=TIMEOUT
        ) as response:
            response.raise_for_status()
            with tmp_path.open("wb") as f_sbml:
                for chunk in response.iter_content(1 << 16):
                    f_sbml.write(chunk)
    except requests.RequestException as err:
        tmp_path.unlink(missing_ok=True)
        raise BioModelsError(f"{model_id}: download failed: {err}") from err
    os.replace(tmp_path, path)
    return path


def load_selection(path: Path) -> Selection:
    """Read a selection file (e.g. `biomodels/models.json`).

    Args:
        path: the selection file.

    Returns:
        The selection.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return Selection(
        date=data["date"], query=data["query"], models=tuple(data["models"])
    )


def write_selection(path: Path, ids: list[str]) -> Selection:
    """Write a selection file with today's date and the given ids.

    Args:
        path: file to write.
        ids: model ids, written sorted and without duplicates.

    Returns:
        The selection written.
    """
    selection = Selection(
        date=date.today().isoformat(),
        query=SEARCH_QUERY,
        models=tuple(sorted(set(ids))),
    )
    path.write_text(
        json.dumps(
            {
                "date": selection.date,
                "query": selection.query,
                "models": list(selection.models),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return selection


def packages(sbml_path: Path) -> tuple[str, ...]:
    """SBML packages an SBML file declares, from the root element's `xmlns`.

    Args:
        sbml_path: SBML file to inspect.

    Returns:
        The package names, sorted and without duplicates.
    """
    with sbml_path.open("rb") as f_sbml:
        head = f_sbml.read(_XMLNS_HEAD).decode("utf-8", errors="replace")
    return tuple(sorted({match.group(2) for match in _XMLNS.finditer(head)}))

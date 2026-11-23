"""Access to the Physiome Model Repository: exposures, workspaces, selection.

The repository (`https://models.physiomeproject.org`) publishes a model as an
*exposure*, a fixed commit of the *workspace* which holds its files. Every
endpoint of the site answers with JSON for the media type of its webservice,
which gives the title, the commit and the files of an exposure; the files
themselves come from the workspace, a git repository which is cloned into the
cache, so that a model which imports another file of its workspace has them
all on disk.

The models are CellML 1.0 and 1.1 documents for the most part, which
libcellml reads in permissive mode (`sbml2cellml.cellml.read_model`).
"""

import json
import logging
import os
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from sbml2cellml.testsuite.cases import cache_dir

logger = logging.getLogger(__name__)

#: root of the Physiome Model Repository
PHYSIOME_URL = "https://models.physiomeproject.org"
#: media type of the webservice, which answers with JSON
JSON_ACCEPT = "application/vnd.physiome.pmr2.json.1"
#: timeout (seconds) of every request and of every git command
TIMEOUT = 120.0
#: how many exposures of the listing are requested at the same time
WORKERS = 8
#: how many models the selection of `query_exposures` holds at most
MAX_MODELS = 100
#: suffix of a CellML file of an exposure
CELLML_SUFFIX = ".cellml"


class PhysiomeError(RuntimeError):
    """A request to the repository failed or a workspace cannot be cloned."""


@dataclass(frozen=True)
class Exposure:
    """One exposure of the repository, the published version of a model."""

    #: id of the exposure, the last segment of its url (`e/5f` is `5f`)
    id: str
    #: title of the exposure
    title: str
    #: url of the workspace, the git repository with the files
    workspace: str
    #: commit of the workspace the exposure publishes
    commit: str
    #: path of the CellML file inside the workspace
    path: str


@dataclass(frozen=True)
class Selection:
    """A snapshot of the exposures of the check, `physiome/models.json`."""

    date: str
    source: str
    models: tuple[Exposure, ...]


def physiome_cache(cache: Path | None = None) -> Path:
    """Cache directory of the workspaces.

    Args:
        cache: cache root, `sbml2cellml.testsuite.cases.cache_dir()` by
            default.

    Returns:
        `<cache>/physiome`.
    """
    return (cache or cache_dir()) / "physiome"


def _get_json(url: str) -> dict:
    """`GET` a url of the repository and parse its JSON body.

    Args:
        url: endpoint to request.

    Returns:
        The parsed JSON body.

    Raises:
        PhysiomeError: if the request fails or the body is no JSON.
    """
    try:
        response = requests.get(
            url, headers={"Accept": JSON_ACCEPT}, timeout=TIMEOUT, allow_redirects=True
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as err:
        raise PhysiomeError(f"Request to {url} failed: {err}") from err


def exposure_urls() -> list[str]:
    """Urls of every exposure of the repository.

    Returns:
        The urls of the listing, in the order of the repository.

    Raises:
        PhysiomeError: if the listing cannot be fetched.
    """
    data = _get_json(f"{PHYSIOME_URL}/exposure")
    links = data.get("collection", {}).get("links", [])
    urls = [
        link["href"]
        for link in links
        if link.get("href", "").startswith(f"{PHYSIOME_URL}/e/")
    ]
    logger.info("%d exposures listed by the repository", len(urls))
    return urls


def exposure(url: str) -> Exposure | None:
    """The exposure of a url, `None` when it publishes no CellML file.

    Args:
        url: url of the exposure, e.g. `https://models.physiomeproject.org/e/5f`.

    Returns:
        The exposure with the first CellML file it links to, `None` when it
        links to none or has no workspace or commit.

    Raises:
        PhysiomeError: if the exposure cannot be fetched.
    """
    collection = _get_json(url).get("collection", {})
    commit = ""
    title = ""
    for item in collection.get("items", []):
        for entry in item.get("data", []):
            if entry.get("name") == "commit_id":
                commit = str(entry.get("value", ""))
            elif entry.get("name") == "title":
                title = " ".join(str(entry.get("value", "")).split())
    workspace = ""
    paths: list[str] = []
    for link in collection.get("links", []):
        href = str(link.get("href", ""))
        if link.get("prompt") == "Workspace URL":
            workspace = href
        elif CELLML_SUFFIX in href and href.endswith("/view"):
            # the link is `<exposure url>/<path in the workspace>/view`
            tail = href[: -len("/view")].split("/e/", 1)[-1]
            paths.append(tail.split("/", 1)[-1])
    if not (commit and workspace and paths):
        return None
    return Exposure(
        id=url.rstrip("/").rsplit("/", 1)[-1],
        title=title,
        workspace=workspace,
        commit=commit,
        path=paths[0],
    )


def _exposure_or_none(url: str) -> Exposure | PhysiomeError | None:
    """`exposure` of a url, its error instead of raising it.

    Args:
        url: url of the exposure.

    Returns:
        The exposure, `None` when it publishes no CellML file, the error
        when the request failed.
    """
    try:
        return exposure(url)
    except PhysiomeError as err:
        return err


def remove_tree(path: Path) -> None:
    """Remove a directory tree, read-only files included.

    git marks the files of its object store read-only, which `os.unlink`
    refuses on windows (`PermissionError: [WinError 5] Access is denied`),
    so a file which cannot be removed is made writable and removed again.

    Args:
        path: the directory to remove.
    """

    def writable(function: Any, name: str, err: BaseException) -> None:
        os.chmod(name, stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onexc=writable)


def _git(arguments: list[str], cwd: Path) -> None:
    """Run a git command in a directory.

    Args:
        arguments: the arguments after `git`.
        cwd: working directory of the command.

    Raises:
        PhysiomeError: if git is missing, times out or fails; the message
            carries the output of the command.
    """
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
        )
    except FileNotFoundError as err:
        raise PhysiomeError(
            "git is needed to clone the workspaces of the repository"
        ) from err
    except subprocess.TimeoutExpired as err:
        raise PhysiomeError(f"git {' '.join(arguments)} timed out") from err
    if completed.returncode != 0:
        raise PhysiomeError(
            f"git {' '.join(arguments)} failed:\n{completed.stdout}{completed.stderr}"
        )


def workspace_dir(exposure: Exposure, cache: Path | None = None) -> Path:
    """Directory of the workspace of an exposure, cloned on first use.

    The repository serves the workspaces over git but refuses a shallow
    fetch, so the whole workspace is cloned (a few megabytes) and checked
    out at the commit of the exposure.

    Args:
        exposure: the exposure.
        cache: cache root, `cache_dir()` by default.

    Returns:
        The directory with the files of the workspace.

    Raises:
        PhysiomeError: if git is missing or the clone fails.
    """
    root = physiome_cache(cache) / exposure.id
    marker = root / ".sbml2cellml-commit"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == (
        exposure.commit
    ):
        return root
    if root.is_dir():
        remove_tree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning workspace %s of exposure %s", exposure.workspace, exposure.id)
    clone = root.with_name(f"{root.name}.clone")
    if clone.is_dir():
        remove_tree(clone)
    clone.mkdir(parents=True)
    _git(["init", "--quiet", "."], clone)
    _git(["remote", "add", "origin", exposure.workspace], clone)
    _git(["fetch", "--quiet", "origin"], clone)
    _git(["checkout", "--quiet", exposure.commit], clone)
    (clone / ".sbml2cellml-commit").write_text(exposure.commit, encoding="utf-8")
    clone.rename(root)
    return root


def model_path(exposure: Exposure, cache: Path | None = None) -> Path:
    """Path of the CellML file of an exposure, cloned on first use.

    Args:
        exposure: the exposure.
        cache: cache root, `cache_dir()` by default.

    Returns:
        The CellML file inside the workspace.

    Raises:
        PhysiomeError: if the workspace cannot be cloned or has no such file.
    """
    path = workspace_dir(exposure, cache) / exposure.path
    if not path.is_file():
        raise PhysiomeError(
            f"Exposure {exposure.id} has no file '{exposure.path}' at commit "
            f"{exposure.commit[:7]}"
        )
    return path


def query_exposures(limit: int = MAX_MODELS) -> list[Exposure]:
    """The exposures of the selection, one per workspace.

    A workspace is published again whenever its model changes, so only the
    first exposure of a workspace is kept; the result is sorted by exposure
    id and cut to `limit` models.

    Args:
        limit: how many exposures to keep at most.

    Returns:
        The exposures with a CellML file.

    Raises:
        PhysiomeError: if the listing cannot be fetched.
    """
    urls = exposure_urls()
    found: list[Exposure | None] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for url, result in zip(urls, pool.map(_exposure_or_none, urls), strict=True):
            if isinstance(result, PhysiomeError):
                logger.warning("Exposure %s cannot be read: %s", url, result)
                continue
            found.append(result)
    exposures: dict[str, Exposure] = {}
    for item in found:
        if item is None or item.workspace in exposures:
            continue
        exposures[item.workspace] = item
    selected = sorted(exposures.values(), key=lambda item: item.id)[:limit]
    logger.info(
        "%d exposures with a CellML file, %d selected", len(exposures), len(selected)
    )
    return selected


def read_selection(path: Path) -> Selection:
    """Read a selection file written by `write_selection`.

    Args:
        path: the JSON file, e.g. `physiome/models.json`.

    Returns:
        The selection.

    Raises:
        PhysiomeError: if the file cannot be read or has no models.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        models = tuple(Exposure(**model) for model in data["models"])
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise PhysiomeError(f"Selection '{path}' cannot be read: {err}") from err
    if not models:
        raise PhysiomeError(f"Selection '{path}' holds no models.")
    return Selection(
        date=str(data.get("date", "")),
        source=str(data.get("source", PHYSIOME_URL)),
        models=models,
    )


def write_selection(models: list[Exposure], path: Path) -> Selection:
    """Write the selection of a `update` run.

    Args:
        models: the exposures of the selection.
        path: the JSON file to write.

    Returns:
        The selection which was written.
    """
    selection = Selection(
        date=date.today().isoformat(),
        source=PHYSIOME_URL,
        models=tuple(models),
    )
    data = {
        "date": selection.date,
        "source": selection.source,
        "models": [vars(model) for model in selection.models],
    }
    Path(path).write_text(
        json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    logger.info("%d models written to '%s'", len(models), path)
    return selection

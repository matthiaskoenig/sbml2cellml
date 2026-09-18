"""Tests of the test suite cases: download, cache, parsing."""

import io
import zipfile
from pathlib import Path

import pytest

from sbml2cellml.testsuite import cases
from sbml2cellml.testsuite.cases import (
    Settings,
    TestSuiteError,
    ensure_suite,
    load_case,
    load_cases,
    parse_model_info,
    parse_settings,
    skip_reason,
)

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"
EVENT_CASE = "00026"
FUNCTION_CASE = "00025"


def test_parse_settings() -> None:
    settings = parse_settings((FIXTURES / "00001" / "00001-settings.txt").read_text())
    assert settings == Settings(
        start=0.0,
        duration=5.0,
        steps=50,
        variables=("S1", "S2"),
        absolute=1e-7,
        relative=1e-4,
        amount=frozenset({"S1", "S2"}),
        concentration=frozenset(),
    )
    assert settings.end == 5.0


def test_parse_settings_missing_key_raises() -> None:
    with pytest.raises(TestSuiteError, match="duration"):
        parse_settings("start: 0\nsteps: 10\nvariables: S1\n")


def test_parse_model_info() -> None:
    info = parse_model_info((FIXTURES / "00001" / "00001-model.m").read_text())
    assert info["testType"] == ["TimeCourse"]
    assert "Amount" in info["testTags"]
    assert "Compartment" in info["componentTags"]
    # the fixture's prose contains a "Note:" line after a blank line, which
    # must not be parsed as a key
    assert "Note" not in info


def test_parse_model_info_ignores_prose_after_header() -> None:
    text = (
        "(*\n"
        "\n"
        "category:      Test\n"
        "testType:      TimeCourse\n"
        "\n"
        "This model does something.\n"
        "\n"
        "It has more than one paragraph of prose.\n"
        "\n"
        "Note: something that looks like a key but is prose.\n"
        "\n"
        "*)\n"
    )
    info = parse_model_info(text)
    assert info == {"category": ["Test"], "testType": ["TimeCourse"]}
    assert "Note" not in info


def test_parse_model_info_tolerates_wrapped_header_value() -> None:
    # a synopsis wrapped onto its own blank-line-separated continuation
    # (as seen in some real cases) must not cut the header short
    text = (
        "(*\n"
        "\n"
        "category:      Test\n"
        "\n"
        "synopsis:      A model\n"
        "\n"
        "               with a wrapped synopsis.\n"
        "\n"
        "componentTags: Compartment\n"
        "\n"
        "testTags:      Amount\n"
        "\n"
        "testType:      TimeCourse\n"
        "\n"
        "\n"
        "\n"
        "Note: earlier versions of this test were different.\n"
        "\n"
        "*)\n"
    )
    info = parse_model_info(text)
    assert info["testType"] == ["TimeCourse"]
    assert info["componentTags"] == ["Compartment"]
    assert info["testTags"] == ["Amount"]


def test_load_case() -> None:
    case = load_case(FIXTURES / "00001")
    assert case.id == "00001"
    assert case.sbml_path == FIXTURES / "00001" / "00001-sbml-l3v2.xml"
    assert case.test_type == "TimeCourse"
    assert list(case.expected.columns) == ["time", "S1", "S2"]
    assert len(case.expected) == 51
    assert skip_reason(case) is None


def test_load_case_renames_time_column(tmp_path: Path) -> None:
    import shutil

    case_dir = tmp_path / "10006"
    shutil.copytree(FIXTURES / "00001", case_dir)
    for f in list(case_dir.iterdir()):
        f.rename(case_dir / f.name.replace("00001", "10006"))
    results = case_dir / "10006-results.csv"
    text = results.read_text()
    assert text.startswith("time,")
    results.write_text("Time," + text.split(",", 1)[1])
    case = load_case(case_dir)
    assert list(case.expected.columns) == ["time", "S1", "S2"]


def test_load_cases_sorted_and_filtered() -> None:
    all_cases = load_cases(FIXTURES)
    assert [c.id for c in all_cases] == sorted(["00001", EVENT_CASE, FUNCTION_CASE])
    assert [c.id for c in load_cases(FIXTURES, ids=[EVENT_CASE])] == [EVENT_CASE]
    assert (
        "EventNoDelay"
        in next(c for c in all_cases if c.id == EVENT_CASE).component_tags
    )
    assert (
        "FunctionDefinition"
        in next(c for c in all_cases if c.id == FUNCTION_CASE).component_tags
    )


def test_skip_reasons(tmp_path: Path) -> None:
    import shutil

    src = FIXTURES / "00001"
    # no L3V2 file
    no_l3v2 = tmp_path / "10001"
    shutil.copytree(src, no_l3v2)
    for f in no_l3v2.iterdir():
        f.rename(no_l3v2 / f.name.replace("00001", "10001"))
    (no_l3v2 / "10001-sbml-l3v2.xml").unlink()
    assert skip_reason(load_case(no_l3v2)) == "no L3V2 file"
    # comp package
    comp = tmp_path / "10002"
    shutil.copytree(src, comp)
    for f in comp.iterdir():
        f.rename(comp / f.name.replace("00001", "10002"))
    m = comp / "10002-model.m"
    m.write_text(
        m.read_text().replace("componentTags: ", "componentTags: comp:Submodel, ")
    )
    assert skip_reason(load_case(comp)) == "package comp"
    # other test type
    other = tmp_path / "10003"
    shutil.copytree(src, other)
    for f in other.iterdir():
        f.rename(other / f.name.replace("00001", "10003"))
    m = other / "10003-model.m"
    m.write_text(
        m.read_text().replace("testType:      TimeCourse", "testType: SteadyState")
    )
    assert skip_reason(load_case(other)) == "test type SteadyState"


def test_ensure_suite_downloads_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a zip with the layout of the release: semantic/00001/...
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for f in (FIXTURES / "00001").iterdir():
            archive.write(f, f"semantic/00001/{f.name}")
    calls: list[str] = []

    class Response:
        def __init__(self) -> None:
            self.content = buffer.getvalue()

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int):
            yield self.content

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_get(url: str, stream: bool, timeout: float) -> Response:
        calls.append(url)
        return Response()

    monkeypatch.setattr(cases.requests, "get", fake_get)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    semantic = ensure_suite()
    assert semantic == tmp_path / "sbml-test-suite" / cases.SUITE_VERSION / "semantic"
    assert (semantic / "00001" / "00001-settings.txt").is_file()
    assert calls == [cases.SUITE_URL.format(version=cases.SUITE_VERSION)]
    ensure_suite()
    assert len(calls) == 1


def test_ensure_suite_corrupt_zip_raises_and_leaves_no_semantic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Response:
        def __init__(self) -> None:
            self.content = b"not a zip file"

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int):
            yield self.content

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_get(url: str, stream: bool, timeout: float) -> Response:
        return Response()

    monkeypatch.setattr(cases.requests, "get", fake_get)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    with pytest.raises(TestSuiteError):
        ensure_suite()
    root = tmp_path / "sbml-test-suite" / cases.SUITE_VERSION
    assert not (root / "semantic").exists()
    assert not (root / "extracting").exists()

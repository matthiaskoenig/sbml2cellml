"""Tests of the metadata in the conversions: the RDF file next to the CellML."""

from pathlib import Path

import libsbml

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.cli import main, main_cellml2sbml
from sbml2cellml.metadata import read_metadata
from sbml2cellml.sbml import validate_document
from tests.conftest import MODELS_DIR
from tests.sbml_models import (
    annotated_model,
    annotated_species,
    simple_model,
    with_history,
    write_sbml,
)


def described_model(mid: str = "described") -> libsbml.Model:
    """`annotated_model` with metadata on every kind of element."""
    model = annotated_model(mid)
    with_history(model)
    annotated_species(model)
    model.getCompartment("cell").setName("hepatocyte")
    model.getParameter("k1").setSBOTerm("SBO:0000035")
    model.getUnitDefinition("mmole").setName("millimole")
    reaction: libsbml.Reaction = model.getReaction("r1")
    reaction.setName("glucose transport")
    reaction.setSBOTerm("SBO:0000655")
    local: libsbml.LocalParameter = reaction.getKineticLaw().createLocalParameter()
    local.setId("unused")
    local.setValue(1.0)
    local.setName("a local parameter")
    return model


def convert(model: libsbml.Model, tmp_path: Path, **kwargs: bool) -> Path:
    """Convert to `<tmp_path>/model.cellml` and return the path of the RDF."""
    sbml_path = write_sbml(tmp_path / "model.xml", model)
    convert_sbml2cellml(sbml_path, cellml_path=tmp_path / "model.cellml", **kwargs)
    return tmp_path / "model.rdf"


def test_sbml2cellml_writes_the_metadata(tmp_path: Path) -> None:
    rdf_path = convert(described_model(), tmp_path)
    records = read_metadata(rdf_path, "model.cellml")
    assert set(records) == {
        "described",
        "cell",
        "k1",
        "S1",
        "r1",
        "r1_unused",
        "units_mmole",
    }
    assert records["cell"].name == "hepatocyte"
    assert records["r1"].name == "glucose transport"
    assert records["r1"].sbo == "SBO:0000655"
    assert records["r1_unused"].name == "a local parameter"
    assert records["units_mmole"].name == "millimole"
    assert "König" in records["described"].terms


def test_model_without_metadata_writes_no_file(tmp_path: Path) -> None:
    assert not convert(simple_model(), tmp_path).exists()


def test_no_metadata_on_request(tmp_path: Path) -> None:
    assert not convert(described_model(), tmp_path, metadata=False).exists()


def test_stale_metadata_is_removed(tmp_path: Path) -> None:
    """The metadata of an earlier conversion would come back in a roundtrip."""
    rdf_path = convert(described_model(), tmp_path)
    assert rdf_path.exists()
    convert(simple_model(), tmp_path)
    assert not rdf_path.exists()


def test_rdf_of_something_else_is_kept(tmp_path: Path) -> None:
    rdf_path = tmp_path / "model.rdf"
    rdf_path.write_text(
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>\n',
        encoding="utf-8",
    )
    convert(simple_model(), tmp_path)
    assert rdf_path.exists()


def test_roundtrip_restores_the_metadata(tmp_path: Path) -> None:
    convert(described_model(), tmp_path)
    doc = convert_cellml2sbml(tmp_path / "model.cellml")
    assert validate_document(doc) == []
    model: libsbml.Model = doc.getModel()

    assert model.getModelHistory().getCreator(0).getFamilyName() == "König"
    species: libsbml.Parameter = model.getParameter("S1")
    assert species.getName() == "glucose & co"
    assert species.getSBOTermID() == "SBO:0000247"
    assert "<b>substrate</b>" in species.getNotesString()
    assert species.getNumCVTerms() == 2
    assert model.getParameter("cell").getName() == "hepatocyte"
    assert model.getParameter("k1").getSBOTermID() == "SBO:0000035"
    reaction: libsbml.Parameter = model.getParameter("r1")
    assert reaction.getName() == "glucose transport"
    assert reaction.getSBOTermID() == "SBO:0000655"
    assert model.getParameter("r1_unused").getName() == "a local parameter"
    assert model.getUnitDefinition("mmole").getName() == "millimole"
    # without metadata the elements have none
    assert not model.getParameter("S2").isSetName()
    assert not model.getParameter("S2").isSetMetaId()


def test_cellml2sbml_ignores_the_metadata_on_request(tmp_path: Path) -> None:
    convert(described_model(), tmp_path)
    doc = convert_cellml2sbml(tmp_path / "model.cellml", metadata=False)
    model: libsbml.Model = doc.getModel()
    assert not model.isSetModelHistory()
    assert not model.getParameter("S1").isSetSBOTerm()


def test_cellml_without_metadata_file_converts(tmp_path: Path) -> None:
    convert(simple_model(), tmp_path)
    doc = convert_cellml2sbml(tmp_path / "model.cellml")
    assert not doc.getModel().getParameter("S1").isSetName()


def test_cli_no_metadata(tmp_path: Path) -> None:
    sbml_path = write_sbml(tmp_path / "model.xml", described_model())
    assert main([str(sbml_path), "--no-metadata"]) == 0
    assert not (tmp_path / "model.rdf").exists()
    assert main([str(sbml_path)]) == 0
    assert (tmp_path / "model.rdf").exists()

    cellml_path = tmp_path / "model.cellml"
    out = tmp_path / "roundtrip.xml"
    assert main_cellml2sbml([str(cellml_path), "-o", str(out), "--no-metadata"]) == 0
    doc = libsbml.readSBMLFromFile(str(out))
    assert not doc.getModel().getParameter("S1").isSetSBOTerm()
    assert main_cellml2sbml([str(cellml_path), "-o", str(out)]) == 0
    doc = libsbml.readSBMLFromFile(str(out))
    assert doc.getModel().getParameter("S1").getSBOTermID() == "SBO:0000247"


def test_roundtrip_of_the_annotated_repressilator(tmp_path: Path) -> None:
    """BIOMD0000000012, SBML level 2 with the annotations of BioModels."""
    cellml_path = tmp_path / "repressilator.cellml"
    convert_sbml2cellml(MODELS_DIR / "repressilator.xml", cellml_path=cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    assert validate_document(doc) == []
    model: libsbml.Model = doc.getModel()

    assert model.getName() == "Elowitz2000 - Repressilator"
    assert "deterministic version of the repressilator" in model.getNotesString()
    assert model.getModelHistory().getNumCreators() == 5
    assert model.getNumCVTerms() == 5
    protein: libsbml.Parameter = model.getParameter("PX")
    assert protein.getName() == "LacI protein"
    assert protein.getSBOTermID() == "SBO:0000252"
    assert "lacI inhibitor" in protein.getNotesString()
    assert (
        protein.getCVTerm(0).getResourceURI(0)
        == "http://identifiers.org/uniprot/P03023"
    )
    reaction: libsbml.Parameter = model.getParameter("Reaction1")
    assert reaction.getName() == "degradation of LacI transcripts"
    assert reaction.getSBOTermID() == "SBO:0000179"
    assert reaction.getNumCVTerms() == 1
    assert model.getUnitDefinition("volume").getName() == "cubic microns"

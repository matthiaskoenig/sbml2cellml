"""Tests of the RDF sidecar with the metadata of an SBML model."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml.metadata import (
    Record,
    apply_metadata,
    collect_metadata,
    element_record,
    read_metadata,
    write_metadata,
)
from sbml2cellml.sbml import validate_document
from tests.sbml_models import (
    XHTML,
    annotated_species,
    cv_term,
    simple_model,
    with_history,
)


def test_record_of_an_element_without_metadata_is_empty() -> None:
    record = element_record(simple_model().getSpecies("S1"))
    assert record == Record()
    assert not record


def test_name_which_is_the_id_is_no_metadata() -> None:
    species: libsbml.Species = simple_model().getSpecies("S1")
    species.setName("S1")
    assert not element_record(species)


def test_record_of_an_annotated_species() -> None:
    record = element_record(annotated_species(simple_model()))
    assert record.name == "glucose & co"
    assert record.sbo == "SBO:0000247"
    assert "<b>substrate</b>" in record.notes
    assert f'xmlns="{XHTML}"' in record.notes
    assert record.terms.count("<bqbiol:is>") == 1
    assert record.terms.count("<bqbiol:isVersionOf>") == 1
    assert "kegg.compound/C00031" in record.terms
    assert not record.is_model


def test_record_of_the_model_has_the_history() -> None:
    model = simple_model()
    with_history(model)
    record = element_record(model)
    assert record.is_model
    assert "<dcterms:creator>" in record.terms
    assert "König" in record.terms
    assert "<dcterms:created" in record.terms
    assert "<bqmodel:isDescribedBy>" in record.terms


def test_level_2_annotations_have_the_same_dialect() -> None:
    """Level 2 writes the history as `dc:creator` with vCard 3."""
    doc = libsbml.SBMLDocument(2, 4)
    model: libsbml.Model = doc.createModel()
    model.setId("level2")
    with_history(model)
    record = element_record(model)
    assert "<dcterms:creator>" in record.terms
    assert "vCard4:family-name" in record.terms
    assert "dc:creator" not in record.terms


def test_collect_metadata_leaves_out_elements_without() -> None:
    model = simple_model()
    records = collect_metadata(
        {"S1": annotated_species(model), "S2": model.getSpecies("S2")}
    )
    assert list(records) == ["S1"]


def write_and_read(records: dict[str, Record], tmp_path: Path) -> dict[str, Record]:
    path = tmp_path / "model.rdf"
    write_metadata(records, "model.cellml", path)
    return read_metadata(path, "model.cellml")


def test_written_file(tmp_path: Path) -> None:
    model = simple_model()
    with_history(model)
    records = collect_metadata({"simple": model, "S1": annotated_species(model)})
    path = tmp_path / "model.rdf"
    write_metadata(records, "model.cellml", path)
    text = path.read_text(encoding="utf-8")
    assert '<rdf:Description rdf:about="model.cellml#S1">' in text
    assert "<dcterms:title>glucose &amp; co</dcterms:title>" in text
    assert '<dcterms:description rdf:parseType="Literal">' in text
    assert 'rdf:resource="https://identifiers.org/SBO:0000247"' in text
    # the SBO term comes before the CV terms
    assert text.index("SBO:0000247") < text.index("CHEBI:17234")
    # deterministic
    write_metadata(records, "model.cellml", tmp_path / "again.rdf")
    assert (tmp_path / "again.rdf").read_text(encoding="utf-8") == text


def test_read_returns_what_was_written(tmp_path: Path) -> None:
    model = simple_model()
    with_history(model)
    records = collect_metadata({"simple": model, "S1": annotated_species(model)})
    read = write_and_read(records, tmp_path)
    assert list(read) == ["simple", "S1"]
    species = read["S1"]
    assert species.name == "glucose & co"
    assert species.sbo == "SBO:0000247"
    assert "substrate" in species.notes
    assert "CHEBI:17234" in species.terms
    assert "SBO:0000247" not in species.terms
    assert "König" in read["simple"].terms


def test_read_ignores_the_subjects_of_other_files(tmp_path: Path) -> None:
    records = collect_metadata({"S1": annotated_species(simple_model())})
    path = tmp_path / "model.rdf"
    write_metadata(records, "other.cellml", path)
    assert read_metadata(path, "model.cellml") == {}


def test_sbo_term_of_the_model_is_a_model_qualifier(tmp_path: Path) -> None:
    model = simple_model()
    model.setSBOTerm("SBO:0000293")
    path = tmp_path / "model.rdf"
    write_metadata(collect_metadata({"simple": model}), "model.cellml", path)
    assert "<bqmodel:is>" in path.read_text(encoding="utf-8")
    read = read_metadata(path, "model.cellml")["simple"]
    assert read.sbo == "SBO:0000293"
    assert read.is_model


def test_sbo_resource_among_the_cv_terms_stays_a_cv_term(tmp_path: Path) -> None:
    """Only the first `is` element with a single SBO resource is the SBO term."""
    species: libsbml.Species = simple_model().getSpecies("S1")
    species.setMetaId("meta_S1")
    species.addCVTerm(
        cv_term(
            libsbml.BQB_IS,
            "https://identifiers.org/CHEBI:17234",
            "https://identifiers.org/SBO:0000247",
        )
    )
    read = write_and_read(collect_metadata({"S1": species}), tmp_path)
    assert read["S1"].sbo == ""
    assert "SBO:0000247" in read["S1"].terms


def target_document() -> tuple[libsbml.SBMLDocument, libsbml.Parameter]:
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId("target")
    parameter: libsbml.Parameter = model.createParameter()
    parameter.setId("S1")
    parameter.setValue(1.0)
    parameter.setConstant(True)
    return doc, parameter


def test_apply_restores_the_metadata_of_a_species(tmp_path: Path) -> None:
    read = write_and_read(
        collect_metadata({"S1": annotated_species(simple_model())}), tmp_path
    )
    doc, parameter = target_document()
    apply_metadata(parameter, read["S1"], "S1")
    assert parameter.getName() == "glucose & co"
    assert parameter.getSBOTermID() == "SBO:0000247"
    assert "<b>substrate</b>" in parameter.getNotesString()
    assert parameter.getMetaId() == "S1"
    assert parameter.getNumCVTerms() == 2
    resources = {
        parameter.getCVTerm(k).getResourceURI(j)
        for k in range(parameter.getNumCVTerms())
        for j in range(parameter.getCVTerm(k).getNumResources())
    }
    assert resources == {
        "https://identifiers.org/CHEBI:17234",
        "https://identifiers.org/CHEBI:4167",
        "https://identifiers.org/kegg.compound/C00031",
    }
    assert validate_document(doc) == []


def test_apply_restores_the_history_of_the_model(tmp_path: Path) -> None:
    model = simple_model()
    with_history(model)
    read = write_and_read(collect_metadata({"simple": model}), tmp_path)
    doc, _ = target_document()
    target: libsbml.Model = doc.getModel()
    apply_metadata(target, read["simple"], "simple")
    assert target.isSetModelHistory()
    history: libsbml.ModelHistory = target.getModelHistory()
    assert history.getCreator(0).getFamilyName() == "König"
    assert history.getCreatedDate().getDateAsString().startswith("2026-09-19T12:00:00")
    assert target.getCVTerm(0).getModelQualifierType() == libsbml.BQM_IS_DESCRIBED_BY
    assert validate_document(doc) == []


def test_apply_of_an_empty_record_changes_nothing() -> None:
    _, parameter = target_document()
    apply_metadata(parameter, Record(), "S1")
    assert not parameter.isSetMetaId()
    assert not parameter.isSetName()
    assert not parameter.isSetNotes()


def test_read_of_a_file_which_is_no_rdf_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.rdf"
    path.write_text("<rdf", encoding="utf-8")
    with pytest.raises(ValueError, match=r"broken\.rdf"):
        read_metadata(path, "model.cellml")

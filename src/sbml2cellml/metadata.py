"""Metadata of an SBML model as RDF next to the CellML model.

CellML 2.0 has no place for metadata: its elements must be in the CellML or
MathML namespace, and the only thing a model offers to the outside is the
`id` of an element. The names, notes, SBO terms, annotations (CV terms) and
the history of the SBML elements therefore go into an RDF/XML file next to
the CellML file, with `<cellml file>#<id>` as the subject of an element, and
`sbml2cellml.cellml2sbml` reads the file back.

The RDF is the one of SBML annotations: `bqbiol` and `bqmodel` qualifiers
with an `rdf:Bag` of resources, the history as `dcterms:creator` (vCard 4),
`dcterms:created` and `dcterms:modified`. libsbml writes and parses it, from
a scratch element of SBML level 3, so that a level 2 model gives the same
RDF. In addition an element has

- `dcterms:title`: its name,
- `dcterms:description`: its notes, the XHTML as an XML literal,
- a first `bqbiol:is` (`bqmodel:is` for the model) with the single resource
  `https://identifiers.org/SBO:...`: its SBO term.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import libsbml

logger = logging.getLogger(__name__)

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCTERMS_NS = "http://purl.org/dc/terms/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
#: prefixes of the RDF of SBML annotations as libsbml writes them
NAMESPACES = {
    "rdf": RDF_NS,
    "dcterms": DCTERMS_NS,
    "vCard": "http://www.w3.org/2001/vcard-rdf/3.0#",
    "vCard4": "http://www.w3.org/2006/vcard/ns#",
    "bqbiol": "http://biomodels.net/biology-qualifiers/",
    "bqmodel": "http://biomodels.net/model-qualifiers/",
}
for _prefix, _uri in NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)

#: resource of an SBO term
SBO_RESOURCE = "https://identifiers.org/"
_SBO_TERM = re.compile(r"SBO:\d{7}$")
#: metaid of the scratch element libsbml writes the RDF of
_SCRATCH_METAID = "metadata"


@dataclass(frozen=True)
class Record:
    """The metadata of one element."""

    #: name of the element, empty when it has none or the name is the id
    name: str = ""
    #: notes, the serialized XHTML children of the `notes` element
    notes: str = ""
    #: SBO term, e.g. `SBO:0000252`
    sbo: str = ""
    #: CV terms and history, the serialized children of the `rdf:Description`
    #: of an SBML annotation
    terms: str = ""
    #: whether the element is the model, whose SBO term is a `bqmodel:is`
    is_model: bool = False

    def __bool__(self) -> bool:
        """Whether the element has any metadata."""
        return bool(self.name or self.notes or self.sbo or self.terms)


def _children(node: libsbml.XMLNode | None) -> str:
    """The serialized children of an XML node of libsbml."""
    if node is None:
        return ""
    return "\n".join(
        node.getChild(k).toXMLString() for k in range(node.getNumChildren())
    )


def _terms(element: libsbml.SBase) -> str:
    """The CV terms and the history of an element as RDF of SBML level 3."""
    has_history = bool(element.isSetModelHistory())
    if element.getNumCVTerms() == 0 and not has_history:
        return ""
    document = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = document.createModel()
    # the qualifiers of a model differ from the ones of the other elements
    scratch: libsbml.SBase = (
        model if isinstance(element, libsbml.Model) else model.createParameter()
    )
    scratch.setMetaId(_SCRATCH_METAID)
    for k in range(element.getNumCVTerms()):
        scratch.addCVTerm(element.getCVTerm(k))
    if has_history:
        scratch.setModelHistory(element.getModelHistory())
    parser = libsbml.RDFAnnotationParser
    annotation: libsbml.XMLNode | None = (
        parser.parseModelHistory(scratch)
        if has_history
        else parser.parseCVTerms(scratch)
    )
    if annotation is None or annotation.getNumChildren() == 0:
        return ""
    rdf: libsbml.XMLNode = annotation.getChild(0)
    return _children(rdf.getChild(0)) if rdf.getNumChildren() else ""


def element_record(element: libsbml.SBase) -> Record:
    """The metadata of an SBML element.

    Args:
        element: the model, a compartment, species, parameter, reaction, ...

    Returns:
        The record, which is false when the element has no metadata.
    """
    name: str = element.getName() if element.isSetName() else ""
    return Record(
        name="" if name == element.getId() else name,
        notes=_children(element.getNotes()) if element.isSetNotes() else "",
        sbo=element.getSBOTermID() if element.isSetSBOTerm() else "",
        terms=_terms(element),
        is_model=isinstance(element, libsbml.Model),
    )


def collect_metadata(elements: dict[str, libsbml.SBase]) -> dict[str, Record]:
    """The records of the elements which have metadata.

    Args:
        elements: SBML element by the id of its CellML element.

    Returns:
        The record by the id of the CellML element, in the order of `elements`.
    """
    records = {cid: element_record(element) for cid, element in elements.items()}
    return {cid: record for cid, record in records.items() if record}


def _indent(text: str, spaces: int) -> str:
    """Indent the lines of a text."""
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _sbo_element(record: Record) -> str:
    """The SBO term of a record as the `is` element of its resource."""
    qualifier = "bqmodel:is" if record.is_model else "bqbiol:is"
    resource = quoteattr(f"{SBO_RESOURCE}{record.sbo}")
    return (
        f"<{qualifier}>\n  <rdf:Bag>\n    <rdf:li rdf:resource={resource}/>\n"
        f"  </rdf:Bag>\n</{qualifier}>"
    )


def write_metadata(records: dict[str, Record], cellml_name: str, path: Path) -> None:
    """Write the records as RDF/XML.

    Args:
        records: record by the id of the CellML element.
        cellml_name: file name of the CellML model, the subjects are
            `<cellml_name>#<id>`.
        path: path of the RDF file.
    """
    declarations = " ".join(
        f'xmlns:{prefix}="{uri}"' for prefix, uri in NAMESPACES.items()
    )
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f"<rdf:RDF {declarations}>"]
    for cid, record in records.items():
        about = quoteattr(f"{cellml_name}#{cid}")
        lines.append(f"  <rdf:Description rdf:about={about}>")
        if record.name:
            lines.append(f"    <dcterms:title>{escape(record.name)}</dcterms:title>")
        if record.notes:
            # an XML literal: the XHTML is not indented, white space is content
            lines.append('    <dcterms:description rdf:parseType="Literal">')
            lines.append(record.notes)
            lines.append("    </dcterms:description>")
        if record.sbo:
            lines.append(_indent(_sbo_element(record), 4))
        if record.terms:
            lines.append(_indent(record.terms, 4))
        lines.append("  </rdf:Description>")
    lines.append("</rdf:RDF>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Metadata of %d elements written to '%s'", len(records), path)


def _serialize(element: ET.Element, default_namespace: str | None = None) -> str:
    """An element as XML, without the text which follows it."""
    copy = ET.Element(element.tag, element.attrib)
    copy.text = element.text
    copy.extend(element)
    try:
        return ET.tostring(
            copy, encoding="unicode", default_namespace=default_namespace
        )
    except ValueError:
        # an element without namespace cannot be written with a default one
        return ET.tostring(copy, encoding="unicode")


def _sbo_term(element: ET.Element) -> str:
    """The SBO term of an `is` element with a single SBO resource, else empty."""
    if element.tag.rpartition("}")[2] != "is":
        return ""
    resources = [
        item.get(f"{{{RDF_NS}}}resource", "")
        for item in element.iter(f"{{{RDF_NS}}}li")
    ]
    if len(resources) != 1:
        return ""
    term = resources[0].rpartition("/")[2]
    return term if _SBO_TERM.match(term) else ""


def read_metadata(path: Path, cellml_name: str) -> dict[str, Record]:
    """Read the records of a CellML model from an RDF/XML file.

    Args:
        path: path of the RDF file, as `write_metadata` writes it.
        cellml_name: file name of the CellML model; the subjects of other
            files are ignored.

    Returns:
        The record by the id of the CellML element.

    Raises:
        ValueError: if the file is not XML.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as err:
        raise ValueError(f"Metadata file '{path}' cannot be read: {err}") from err
    records: dict[str, Record] = {}
    for description in root.iter(f"{{{RDF_NS}}}Description"):
        file_name, _, cid = description.get(f"{{{RDF_NS}}}about", "").partition("#")
        if file_name != cellml_name or not cid:
            continue
        name = notes = sbo = ""
        is_model = False
        terms: list[str] = []
        for child in description:
            if child.tag == f"{{{DCTERMS_NS}}}title":
                name = child.text or ""
            elif child.tag == f"{{{DCTERMS_NS}}}description":
                notes = "\n".join(_serialize(note, XHTML_NS) for note in child)
            elif not sbo and not terms and _sbo_term(child):
                sbo = _sbo_term(child)
                is_model = child.tag.startswith(f"{{{NAMESPACES['bqmodel']}}}")
            else:
                terms.append(_serialize(child))
        records[cid] = Record(name, notes, sbo, "\n".join(terms), is_model)
    return records


def apply_metadata(element: libsbml.SBase, record: Record, metaid: str) -> None:
    """Set the metadata of a record on an SBML element.

    Args:
        element: the SBML element.
        record: its metadata.
        metaid: metaid the element gets when it has CV terms or a history,
            unique in the document.
    """
    if record.name:
        element.setName(record.name)
    if record.sbo:
        element.setSBOTerm(record.sbo)
    statuses: dict[str, int] = {}
    if record.notes:
        statuses["notes"] = element.setNotes(f"<notes>{record.notes}</notes>")
    if record.terms:
        declarations = " ".join(
            f'xmlns:{prefix}="{uri}"' for prefix, uri in NAMESPACES.items()
        )
        element.setMetaId(metaid)
        statuses["annotation"] = element.setAnnotation(
            f"<annotation><rdf:RDF {declarations}>"
            f'<rdf:Description rdf:about="#{metaid}">{record.terms}'
            "</rdf:Description></rdf:RDF></annotation>"
        )
    for what, status in statuses.items():
        if status != libsbml.LIBSBML_OPERATION_SUCCESS:
            logger.warning(
                "The %s of '%s' could not be set: %s",
                what,
                element.getId(),
                libsbml.OperationReturnValue_toString(status),
            )

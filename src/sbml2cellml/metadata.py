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

An event carries more than its metadata: CellML applies a reset when its
test variable reaches its test value, so the delay of an event, its
priority, and the `persistent`, `initialValue` and
`useValuesFromTriggerTime` flags of SBML have no counterpart in the model.
They are written in the namespace of this package under the subject of the
trigger variable of the event, `<event>_trigger`, which the conversion back
to SBML applies to the event of its resets, so that an event survives the
roundtrip:

```xml
<sbml2cellml:event>
  <sbml2cellml:delay rdf:parseType="Literal"><math ...>...</math></sbml2cellml:delay>
  <sbml2cellml:priority rdf:parseType="Literal"><math ...>...</math></sbml2cellml:priority>
  <sbml2cellml:persistent>false</sbml2cellml:persistent>
  <sbml2cellml:initialValue>false</sbml2cellml:initialValue>
  <sbml2cellml:useValuesFromTriggerTime>false</sbml2cellml:useValuesFromTriggerTime>
</sbml2cellml:event>
```
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
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
#: namespace of what SBML has and CellML cannot express, the attributes of
#: an event
SBML2CELLML_NS = "https://matthiaskoenig.github.io/sbml2cellml/rdf#"
#: prefixes of the RDF of SBML annotations as libsbml writes them
NAMESPACES = {
    "rdf": RDF_NS,
    "dcterms": DCTERMS_NS,
    "vCard": "http://www.w3.org/2001/vcard-rdf/3.0#",
    "vCard4": "http://www.w3.org/2006/vcard/ns#",
    "bqbiol": "http://biomodels.net/biology-qualifiers/",
    "bqmodel": "http://biomodels.net/model-qualifiers/",
    "sbml2cellml": SBML2CELLML_NS,
}
for _prefix, _uri in NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)
# the mathematics of a delay or a priority is written without a prefix, as
# libsbml writes it: a default namespace is no option for an element with an
# attribute which has none, e.g. the `type` of a number
ET.register_namespace("", MATHML_NS)

#: resource of an SBO term
SBO_RESOURCE = "https://identifiers.org/"
_SBO_TERM = re.compile(r"SBO:\d{7}$")
#: metaid of the scratch element libsbml writes the RDF of
_SCRATCH_METAID = "metadata"


@dataclass(frozen=True)
class EventRecord:
    """What an SBML event has and the resets of CellML cannot express.

    The resets of the CellML model hold the trigger and the assignments of
    an event; its delay, its priority and the three flags of SBML are kept
    here, so that `cellml2sbml` writes the event the model was converted
    from.
    """

    #: the delay, the serialized `math` element, empty without one
    delay: str = ""
    #: the priority, the serialized `math` element, empty without one
    priority: str = ""
    #: whether the trigger is persistent, i.e. the event fires even when the
    #: trigger does not hold any more when it is executed
    persistent: bool = True
    #: the value of the trigger before the start time, which decides whether
    #: an event whose trigger holds at the start fires there
    initial_value: bool = True
    #: whether the assignments take the values of the time of the trigger
    use_values_from_trigger_time: bool = True

    def __bool__(self) -> bool:
        """Whether the event has anything a reset cannot express."""
        return bool(
            self.delay
            or self.priority
            or not self.persistent
            or not self.initial_value
            or not self.use_values_from_trigger_time
        )


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
    #: of an event: what its resets cannot express
    event: EventRecord | None = None

    def __bool__(self) -> bool:
        """Whether the element has any metadata."""
        return bool(self.name or self.notes or self.sbo or self.terms or self.event)


def _prefixes(node: libsbml.XMLNode, prefixes: dict[str, str]) -> None:
    """Collect the namespace of every prefix of the elements and attributes."""
    if node.getPrefix():
        prefixes.setdefault(node.getPrefix(), node.getURI())
    attributes: libsbml.XMLAttributes = node.getAttributes()
    for k in range(attributes.getLength()):
        if attributes.getPrefix(k):
            prefixes.setdefault(attributes.getPrefix(k), attributes.getURI(k))
    for k in range(node.getNumChildren()):
        _prefixes(node.getChild(k), prefixes)


def _children(node: libsbml.XMLNode | None) -> str:
    """The serialized children of an XML node of libsbml.

    A child declares the prefixes it uses: the declaration of a model may be
    on an element outside of the node, e.g. `xmlns:html` on the `sbml`
    element for the notes, and would be lost.
    """
    if node is None:
        return ""
    fragments = []
    for k in range(node.getNumChildren()):
        child = libsbml.XMLNode(node.getChild(k))
        prefixes: dict[str, str] = {}
        _prefixes(child, prefixes)
        for prefix, uri in prefixes.items():
            # the container declares the prefixes of the RDF of SBML; by
            # prefix, libsbml gives its own `bqbiol` nodes another namespace
            # (`biological-qualifiers`) than it declares
            declared = prefix in NAMESPACES or child.hasNamespacePrefix(prefix)
            if uri and not declared:
                child.addNamespace(uri, prefix)
        fragments.append(child.toXMLString())
    return "\n".join(fragments)


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


def _math_of(element: libsbml.Delay | libsbml.Priority | None) -> str:
    """The `math` element of a delay or a priority, empty without one.

    The calls of the function definitions of the model are expanded, as the
    conversion expands them everywhere else: the model the metadata is
    applied to has no function definitions, CellML has no functions.
    """
    if element is None or not element.isSetMath():
        return ""
    math_node: libsbml.ASTNode = element.getMath().deepCopy()
    model: libsbml.Model | None = element.getModel()
    if model is not None and model.getNumFunctionDefinitions():
        libsbml.SBMLTransforms.replaceFD(
            math_node, model.getListOfFunctionDefinitions()
        )
    return (
        libsbml.writeMathMLToString(math_node)
        .strip()
        .removeprefix('<?xml version="1.0" encoding="UTF-8"?>')
        .strip()
    )


def event_record(event: libsbml.Event) -> EventRecord:
    """What an SBML event has and the resets of CellML cannot express.

    Args:
        event: the SBML event.

    Returns:
        Its delay, its priority and its flags.
    """
    trigger: libsbml.Trigger | None = event.getTrigger()
    return EventRecord(
        delay=_math_of(event.getDelay()),
        priority=_math_of(event.getPriority()),
        persistent=True if trigger is None else trigger.getPersistent(),
        initial_value=True if trigger is None else trigger.getInitialValue(),
        use_values_from_trigger_time=event.getUseValuesFromTriggerTime(),
    )


def element_record(element: libsbml.SBase) -> Record:
    """The metadata of an SBML element.

    An event carries what its resets cannot express as well
    (`event_record`).

    Args:
        element: the model, a compartment, species, parameter, reaction, ...

    Returns:
        The record, which is false when the element has no metadata.
    """
    name: str = element.getName() if element.isSetName() else ""
    event = event_record(element) if isinstance(element, libsbml.Event) else None
    return Record(
        name="" if name == element.getId() else name,
        notes=_children(element.getNotes()) if element.isSetNotes() else "",
        sbo=element.getSBOTermID() if element.isSetSBOTerm() else "",
        terms=_terms(element),
        is_model=isinstance(element, libsbml.Model),
        event=event if event else None,
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
    # the namespace of this project is declared for a model with an event,
    # the RDF of a model without one is the RDF of SBML annotations alone
    prefixes = {
        prefix: uri
        for prefix, uri in NAMESPACES.items()
        if prefix != "sbml2cellml" or any(record.event for record in records.values())
    }
    declarations = " ".join(
        f'xmlns:{prefix}="{uri}"' for prefix, uri in prefixes.items()
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
        if record.event:
            lines.extend(_event_lines(record.event))
        lines.append("  </rdf:Description>")
    lines.append("</rdf:RDF>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Metadata of %d elements written to '%s'", len(records), path)


def _event_lines(event: EventRecord) -> list[str]:
    """The lines of the attributes of an event a reset cannot express."""
    lines = ["    <sbml2cellml:event>"]
    for name, math in (("delay", event.delay), ("priority", event.priority)):
        if math:
            # an XML literal: the MathML is the mathematics of the event
            lines.append(f'      <sbml2cellml:{name} rdf:parseType="Literal">')
            lines.append(_indent(math, 8))
            lines.append(f"      </sbml2cellml:{name}>")
    for name, flag in (
        ("persistent", event.persistent),
        ("initialValue", event.initial_value),
        ("useValuesFromTriggerTime", event.use_values_from_trigger_time),
    ):
        if not flag:
            lines.append(f"      <sbml2cellml:{name}>false</sbml2cellml:{name}>")
    lines.append("    </sbml2cellml:event>")
    return lines


def _event_of(element: ET.Element) -> EventRecord:
    """The attributes of an event from its `sbml2cellml:event` element."""
    values: dict[str, str] = {}
    maths: dict[str, str] = {}
    for child in element:
        name = child.tag.rpartition("}")[2]
        if name in ("delay", "priority"):
            maths[name] = "\n".join(_serialize(math) for math in child)
        else:
            values[name] = (child.text or "").strip()
    return EventRecord(
        delay=maths.get("delay", ""),
        priority=maths.get("priority", ""),
        persistent=values.get("persistent", "true") != "false",
        initial_value=values.get("initialValue", "true") != "false",
        use_values_from_trigger_time=(
            values.get("useValuesFromTriggerTime", "true") != "false"
        ),
    )


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
        event: EventRecord | None = None
        terms: list[str] = []
        for child in description:
            if child.tag == f"{{{DCTERMS_NS}}}title":
                name = child.text or ""
            elif child.tag == f"{{{DCTERMS_NS}}}description":
                notes = "\n".join(_serialize(note, XHTML_NS) for note in child)
            elif child.tag == f"{{{SBML2CELLML_NS}}}event":
                event = _event_of(child)
            elif not sbo and not terms and _sbo_term(child):
                sbo = _sbo_term(child)
                is_model = child.tag.startswith(f"{{{NAMESPACES['bqmodel']}}}")
            else:
                terms.append(_serialize(child))
        records[cid] = Record(name, notes, sbo, "\n".join(terms), is_model, event)
    return records


def apply_event(event: libsbml.Event, record: EventRecord) -> None:
    """Set what a reset cannot express on the event of the resets.

    Args:
        event: the SBML event of the resets of the trigger variable.
        record: the delay, the priority and the flags of the original
            event.
    """
    for name, math_text in (("delay", record.delay), ("priority", record.priority)):
        if not math_text:
            continue
        math_node: libsbml.ASTNode | None = libsbml.readMathMLFromString(math_text)
        if math_node is None:
            logger.warning("The %s of event '%s' cannot be read", name, event.getId())
            continue
        element = event.createDelay() if name == "delay" else event.createPriority()
        element.setMath(math_node)
    trigger: libsbml.Trigger | None = event.getTrigger()
    if trigger is not None:
        trigger.setPersistent(record.persistent)
        trigger.setInitialValue(record.initial_value)
    event.setUseValuesFromTriggerTime(record.use_values_from_trigger_time)


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

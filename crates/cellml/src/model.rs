//! The data model of a CellML document and its reader.

use crate::math::{self, MathError, Node};
use roxmltree::Node as X;
use thiserror::Error;

/// The namespace of CellML 1.0.
pub const CELLML_NS_1_0: &str = "http://www.cellml.org/cellml/1.0#";
/// The namespace of CellML 1.1.
pub const CELLML_NS_1_1: &str = "http://www.cellml.org/cellml/1.1#";
/// The namespace of CellML 2.0.
pub const CELLML_NS_2_0: &str = "http://www.cellml.org/cellml/2.0#";
/// The namespace of XLink, which holds the href of an import.
pub const XLINK_NS: &str = "http://www.w3.org/1999/xlink";
/// The namespace of the metadata of CellML 1.0 and 1.1, which holds the
/// `cmeta:id` of an element; CellML 2.0 writes the id as the attribute `id`.
pub const CMETA_NS: &str = "http://www.cellml.org/metadata/1.0#";

/// The version of a CellML document.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Version {
    /// CellML 1.0.
    V1_0,
    /// CellML 1.1, which added the imports.
    V1_1,
    /// CellML 2.0.
    V2_0,
}

impl Version {
    /// The namespace of the version.
    pub fn namespace(self) -> &'static str {
        match self {
            Self::V1_0 => CELLML_NS_1_0,
            Self::V1_1 => CELLML_NS_1_1,
            Self::V2_0 => CELLML_NS_2_0,
        }
    }

    /// The version of a namespace, `None` for any other namespace.
    pub fn from_namespace(namespace: &str) -> Option<Self> {
        match namespace {
            CELLML_NS_1_0 => Some(Self::V1_0),
            CELLML_NS_1_1 => Some(Self::V1_1),
            CELLML_NS_2_0 => Some(Self::V2_0),
            _ => None,
        }
    }

    /// Whether the version is 1.0 or 1.1, which name the interfaces of a
    /// variable differently and group the components instead of
    /// encapsulating them.
    pub fn is_1x(self) -> bool {
        self != Self::V2_0
    }
}

/// A failure to read a document.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum ReadError {
    /// The text is no XML document.
    #[error("the document is not XML: {0}")]
    Xml(String),
    /// The root element is no CellML model.
    #[error("the root element is '{element}' of '{namespace}', not a CellML model")]
    NotCellML {
        /// The name of the root element.
        element: String,
        /// Its namespace, empty when it has none.
        namespace: String,
    },
    /// An element without an attribute it needs.
    #[error("a '{element}' element has no '{attribute}' attribute")]
    MissingAttribute {
        /// The name of the element.
        element: String,
        /// The name of the attribute.
        attribute: String,
    },
    /// An attribute whose text is no number.
    #[error("the '{attribute}' of a '{element}' element is '{text}', not a number")]
    NotANumber {
        /// The name of the element.
        element: String,
        /// The name of the attribute.
        attribute: String,
        /// The text of the attribute.
        text: String,
    },
    /// The mathematics of a component cannot be read.
    #[error("the mathematics of the component '{component}' cannot be read: {source}")]
    Math {
        /// The name of the component.
        component: String,
        /// What the reader of the MathML says.
        source: MathError,
    },
}

/// A unit of a unit definition.
#[derive(Debug, Clone, PartialEq)]
pub struct Unit {
    /// The units this one is built from, a name of the model or of the
    /// built in units of CellML.
    pub units: String,
    /// The prefix, a name such as `milli` or an exponent of ten as text.
    pub prefix: Option<String>,
    /// The exponent, 1 without one.
    pub exponent: f64,
    /// The multiplier, 1 without one.
    pub multiplier: f64,
    /// The offset, 0 without one; CellML 2.0 has no offset.
    pub offset: f64,
}

/// A unit definition of a model or, in CellML 1.0 and 1.1, of a component.
#[derive(Debug, Clone, PartialEq)]
pub struct Units {
    /// The name.
    pub name: String,
    /// The id of the element, which the metadata of a document points at.
    pub id: Option<String>,
    /// Whether the definition declares new base units (CellML 1.0 and 1.1).
    pub base_units: bool,
    /// The units it is built from, empty for base units and for an import.
    pub units: Vec<Unit>,
    /// Where the definition is imported from, `None` for one of this
    /// document.
    pub import: Option<ImportRef>,
}

/// What a variable of CellML 2.0 exposes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Interface {
    /// No interface, the default.
    None,
    /// `public`, to the siblings of the component.
    Public,
    /// `private`, to the components it encapsulates.
    Private,
    /// `public_and_private`.
    PublicAndPrivate,
}

impl Interface {
    /// The interface of the text of the attribute, `None` for any other text.
    fn from_text(text: &str) -> Self {
        match text {
            "public" => Self::Public,
            "private" => Self::Private,
            "public_and_private" => Self::PublicAndPrivate,
            _ => Self::None,
        }
    }

    /// Whether the interface exposes the variable to the siblings.
    pub fn is_public(self) -> bool {
        matches!(self, Self::Public | Self::PublicAndPrivate)
    }

    /// Whether the interface exposes the variable to the children.
    pub fn is_private(self) -> bool {
        matches!(self, Self::Private | Self::PublicAndPrivate)
    }
}

/// The direction of an interface of CellML 1.0 and 1.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    /// No interface, the default.
    None,
    /// `in`, the variable takes its value from the connection.
    In,
    /// `out`, the variable gives its value to the connection.
    Out,
}

impl Direction {
    /// The direction of the text of the attribute, `None` for any other text.
    fn from_text(text: &str) -> Self {
        match text {
            "in" => Self::In,
            "out" => Self::Out,
            _ => Self::None,
        }
    }

    /// Whether the variable is connected through this interface.
    pub fn is_connected(self) -> bool {
        self != Self::None
    }
}

/// A variable of a component.
#[derive(Debug, Clone, PartialEq)]
pub struct Variable {
    /// The name, unique in its component.
    pub name: String,
    /// The id of the element, which the metadata of a document points at.
    pub id: Option<String>,
    /// The name of its units.
    pub units: String,
    /// The initial value as it is written: a number, or the name of
    /// another variable of the component (CellML 2.0).
    pub initial_value: Option<String>,
    /// The `interface` of CellML 2.0, `None` in a document of CellML 1.0
    /// and 1.1, which has the two directions instead.
    pub interface: Interface,
    /// The `public_interface` of CellML 1.0 and 1.1.
    pub public_interface: Direction,
    /// The `private_interface` of CellML 1.0 and 1.1.
    pub private_interface: Direction,
}

impl Variable {
    /// Whether the variable is exposed to the siblings of its component,
    /// whatever the version of the document writes it as.
    pub fn is_public(&self) -> bool {
        self.interface.is_public() || self.public_interface.is_connected()
    }

    /// Whether the variable is exposed to the components its component
    /// encapsulates.
    pub fn is_private(&self) -> bool {
        self.interface.is_private() || self.private_interface.is_connected()
    }
}

/// Where an imported component or unit definition comes from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportRef {
    /// The index of the import in [`Model::imports`].
    pub import: usize,
    /// The name the component or the unit definition has in the imported
    /// document (`component_ref` or `units_ref`).
    pub reference: String,
}

/// A component of a model.
#[derive(Debug, Clone, PartialEq)]
pub struct Component {
    /// The name, unique in its model.
    pub name: String,
    /// Where the component is imported from, `None` for one of this
    /// document; an imported component has no variables and no
    /// mathematics until the import is resolved, as in libcellml.
    pub import: Option<ImportRef>,
    /// Its variables, in the order of the document.
    pub variables: Vec<Variable>,
    /// The equations of its `<math>` elements, in the order of the document.
    pub math: Vec<Node>,
    /// The unit definitions inside the component (CellML 1.0 and 1.1).
    pub units: Vec<Units>,
    /// The resets of the component (CellML 2.0).
    pub resets: Vec<Reset>,
}

impl Component {
    /// The index of a variable of the component by its name.
    pub fn variable(&self, name: &str) -> Option<usize> {
        self.variables.iter().position(|v| v.name == name)
    }
}

/// A reset of a component (CellML 2.0): when the test variable reaches the
/// test value, the variable takes the reset value.
#[derive(Debug, Clone, PartialEq)]
pub struct Reset {
    /// The name of the variable the reset sets, in its component.
    pub variable: String,
    /// The name of the variable the reset tests.
    pub test_variable: String,
    /// The order, which decides which of several resets is applied first,
    /// the lowest first.
    pub order: i32,
    /// The mathematics of the test value, the expression itself or the
    /// equation `test_variable = expression`.
    pub test_value: Option<Node>,
    /// The mathematics of the reset value, written the same way.
    pub reset_value: Option<Node>,
}

/// A connection of two components and the variables it maps.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Connection {
    /// The name of the first component.
    pub component_1: String,
    /// The name of the second component.
    pub component_2: String,
    /// The variable of the first and the one of the second component, one
    /// pair per `<map_variables>`.
    pub variables: Vec<(String, String)>,
}

/// A component of the encapsulation tree with the components it encapsulates.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComponentRef {
    /// The name of the component.
    pub component: String,
    /// The components it encapsulates.
    pub children: Vec<ComponentRef>,
}

/// A component or a unit definition of another document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportedItem {
    /// The name it has in this model.
    pub name: String,
    /// The name it has in the imported document (`component_ref` or
    /// `units_ref`).
    pub reference: String,
}

/// An import of components and unit definitions of another document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Import {
    /// The `xlink:href` of the import, relative to the document.
    pub href: String,
    /// The imported components.
    pub components: Vec<ImportedItem>,
    /// The imported unit definitions.
    pub units: Vec<ImportedItem>,
}

/// A model.
#[derive(Debug, Clone, PartialEq)]
pub struct Model {
    /// The name.
    pub name: String,
    /// The id of the element, which the metadata of a document points at.
    pub id: Option<String>,
    /// The unit definitions of the model.
    pub units: Vec<Units>,
    /// The components, in the order of the document.
    pub components: Vec<Component>,
    /// The connections, in the order of the document.
    pub connections: Vec<Connection>,
    /// The encapsulation, the roots of the tree; a model of CellML 1.0 or
    /// 1.1 writes it as the groups of the relationship `encapsulation`.
    pub encapsulation: Vec<ComponentRef>,
    /// The imports, in the order of the document.
    pub imports: Vec<Import>,
}

impl Model {
    /// The index of a component of the model by its name.
    pub fn component(&self, name: &str) -> Option<usize> {
        self.components.iter().position(|c| c.name == name)
    }

    /// The parent of every encapsulated component, `(child, parent)`.
    pub fn encapsulation_parents(&self) -> Vec<(String, String)> {
        let mut parents = Vec::new();
        let mut stack: Vec<&ComponentRef> = self.encapsulation.iter().collect();
        while let Some(reference) = stack.pop() {
            for child in &reference.children {
                parents.push((child.component.clone(), reference.component.clone()));
                stack.push(child);
            }
        }
        parents.sort();
        parents
    }
}

/// A document and the version it is written in.
#[derive(Debug, Clone, PartialEq)]
pub struct Document {
    /// The version of CellML.
    pub version: Version,
    /// The model of the document.
    pub model: Model,
}

/// Read a CellML document.
///
/// The reader takes a document of any version of CellML and keeps what it
/// holds, it validates nothing: a model of CellML 1.0 is read with its
/// interfaces and its groups, one of CellML 2.0 with its interfaces and
/// its encapsulation, and both give the same [`Model`].
///
/// # Arguments
///
/// * `text` - the text of the document.
///
/// # Errors
///
/// Returns a [`ReadError`] when the text is no XML, when its root element
/// is no CellML model, when an element misses an attribute it needs or
/// when the mathematics of a component cannot be read.
pub fn read(text: &str) -> Result<Document, ReadError> {
    let document =
        roxmltree::Document::parse(text).map_err(|err| ReadError::Xml(err.to_string()))?;
    let root = document.root_element();
    let namespace = root.tag_name().namespace().unwrap_or_default();
    let version = Version::from_namespace(namespace).filter(|_| root.tag_name().name() == "model");
    let Some(version) = version else {
        return Err(ReadError::NotCellML {
            element: root.tag_name().name().to_string(),
            namespace: namespace.to_string(),
        });
    };
    Ok(Document {
        version,
        model: model(root, version)?,
    })
}

/// The attribute of an element, an error when it has none.
fn attribute(node: X, name: &str) -> Result<String, ReadError> {
    node.attribute(name)
        .map(str::to_string)
        .ok_or_else(|| ReadError::MissingAttribute {
            element: node.tag_name().name().to_string(),
            attribute: name.to_string(),
        })
}

/// The id of an element: the attribute `id` of CellML 2.0, the `cmeta:id`
/// of CellML 1.0 and 1.1, `None` when it has neither.
fn element_id(node: X) -> Option<String> {
    node.attribute("id")
        .or_else(|| node.attribute((CMETA_NS, "id")))
        .map(str::to_string)
        .filter(|id| !id.is_empty())
}

/// A numeric attribute of an element, its default when it has none.
fn number(node: X, name: &str, default: f64) -> Result<f64, ReadError> {
    match node.attribute(name) {
        None => Ok(default),
        Some(text) => text
            .trim()
            .parse::<f64>()
            .map_err(|_| ReadError::NotANumber {
                element: node.tag_name().name().to_string(),
                attribute: name.to_string(),
                text: text.to_string(),
            }),
    }
}

/// The elements of a node which are CellML elements of the version.
fn children<'a>(node: X<'a, 'a>, version: Version) -> impl Iterator<Item = X<'a, 'a>> {
    node.children().filter(move |child| {
        child.is_element() && child.tag_name().namespace() == Some(version.namespace())
    })
}

/// The model of the root element.
fn model(root: X, version: Version) -> Result<Model, ReadError> {
    let mut model = Model {
        name: root.attribute("name").unwrap_or_default().to_string(),
        id: element_id(root),
        units: Vec::new(),
        components: Vec::new(),
        connections: Vec::new(),
        encapsulation: Vec::new(),
        imports: Vec::new(),
    };
    for child in children(root, version) {
        match child.tag_name().name() {
            "units" => model.units.push(units(child, version)?),
            "component" => model.components.push(component(child, version)?),
            "connection" => model.connections.push(connection(child, version)?),
            "encapsulation" => model.encapsulation.extend(component_refs(child, version)?),
            "group" => {
                if is_encapsulation(child, version) {
                    model.encapsulation.extend(component_refs(child, version)?);
                }
            }
            "import" => {
                let element = import(child, version)?;
                let index = model.imports.len();
                // an imported component is a component of this model
                // without a content, as libcellml reads it
                for item in &element.components {
                    model.components.push(Component {
                        name: item.name.clone(),
                        import: Some(ImportRef {
                            import: index,
                            reference: item.reference.clone(),
                        }),
                        variables: Vec::new(),
                        math: Vec::new(),
                        units: Vec::new(),
                        resets: Vec::new(),
                    });
                }
                for item in &element.units {
                    model.units.push(Units {
                        name: item.name.clone(),
                        id: None,
                        base_units: false,
                        units: Vec::new(),
                        import: Some(ImportRef {
                            import: index,
                            reference: item.reference.clone(),
                        }),
                    });
                }
                model.imports.push(element);
            }
            _ => {}
        }
    }
    if version.is_1x() {
        normalize_builtin_units(&mut model);
    }
    Ok(model)
}

/// The built in units CellML 2.0 renamed, by their name in CellML 1.0 and 1.1.
const RENAMED_UNITS: [(&str, &str); 2] = [("meter", "metre"), ("liter", "litre")];

/// Give the built in units of a model of CellML 1.0 or 1.1 their CellML
/// 2.0 names, as libcellml does when it reads such a document.
///
/// A reference to `meter` or `liter` becomes one to `metre` or `litre`,
/// unless the model defines units of that name, which then are its own
/// units and no built in ones.
fn normalize_builtin_units(model: &mut Model) {
    let defined: Vec<String> = model
        .units
        .iter()
        .map(|units| units.name.clone())
        .chain(
            model
                .components
                .iter()
                .flat_map(|component| component.units.iter().map(|units| units.name.clone())),
        )
        .collect();
    let renamed: Vec<(&str, &str)> = RENAMED_UNITS
        .into_iter()
        .filter(|(old, _)| !defined.iter().any(|name| name == old))
        .collect();
    if renamed.is_empty() {
        return;
    }
    let rename = |name: &mut String| {
        if let Some((_, new)) = renamed.iter().find(|(old, _)| name == old) {
            *name = (*new).to_string();
        }
    };
    for component in &mut model.components {
        for variable in &mut component.variables {
            rename(&mut variable.units);
        }
        for units in &mut component.units {
            for unit in &mut units.units {
                rename(&mut unit.units);
            }
        }
    }
    for units in &mut model.units {
        for unit in &mut units.units {
            rename(&mut unit.units);
        }
    }
}

/// A unit definition and the units it is built from.
fn units(node: X, version: Version) -> Result<Units, ReadError> {
    let mut definition = Units {
        name: attribute(node, "name")?,
        id: element_id(node),
        base_units: node.attribute("base_units") == Some("yes"),
        units: Vec::new(),
        import: None,
    };
    for child in children(node, version).filter(|c| c.tag_name().name() == "unit") {
        definition.units.push(Unit {
            units: attribute(child, "units")?,
            prefix: child.attribute("prefix").map(str::to_string),
            exponent: number(child, "exponent", 1.0)?,
            multiplier: number(child, "multiplier", 1.0)?,
            offset: number(child, "offset", 0.0)?,
        });
    }
    Ok(definition)
}

/// A component with its variables, its mathematics and its unit definitions.
fn component(node: X, version: Version) -> Result<Component, ReadError> {
    let name = attribute(node, "name")?;
    let mut component = Component {
        name: name.clone(),
        import: None,
        variables: Vec::new(),
        math: Vec::new(),
        units: Vec::new(),
        resets: Vec::new(),
    };
    for child in children(node, version) {
        match child.tag_name().name() {
            "variable" => component.variables.push(Variable {
                name: attribute(child, "name")?,
                id: element_id(child),
                units: attribute(child, "units")?,
                initial_value: child.attribute("initial_value").map(str::to_string),
                interface: Interface::from_text(child.attribute("interface").unwrap_or_default()),
                public_interface: Direction::from_text(
                    child.attribute("public_interface").unwrap_or_default(),
                ),
                private_interface: Direction::from_text(
                    child.attribute("private_interface").unwrap_or_default(),
                ),
            }),
            "units" => component.units.push(units(child, version)?),
            "reset" => component.resets.push(reset(child, version, &name)?),
            _ => {}
        }
    }
    for child in node
        .children()
        .filter(|child| child.is_element() && child.tag_name().namespace() == Some(math::MATHML_NS))
    {
        component.math.extend(
            math::equations(child, version.namespace()).map_err(|source| ReadError::Math {
                component: name.clone(),
                source,
            })?,
        );
    }
    Ok(component)
}

/// A reset and the mathematics of its two values.
fn reset(node: X, version: Version, component: &str) -> Result<Reset, ReadError> {
    let mut reset = Reset {
        variable: attribute(node, "variable")?,
        test_variable: attribute(node, "test_variable")?,
        order: node
            .attribute("order")
            .and_then(|text| text.trim().parse().ok())
            .unwrap_or(0),
        test_value: None,
        reset_value: None,
    };
    for child in children(node, version) {
        let name = child.tag_name().name();
        if !matches!(name, "test_value" | "reset_value") {
            continue;
        }
        let math = child
            .children()
            .filter(|child| {
                child.is_element() && child.tag_name().namespace() == Some(math::MATHML_NS)
            })
            .map(|element| math::equations(element, version.namespace()))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|source| ReadError::Math {
                component: component.to_string(),
                source,
            })?
            .into_iter()
            .flatten()
            .next();
        if name == "test_value" {
            reset.test_value = math;
        } else {
            reset.reset_value = math;
        }
    }
    Ok(reset)
}

/// A connection, the components of CellML 2.0 or of its `<map_components>`.
fn connection(node: X, version: Version) -> Result<Connection, ReadError> {
    let mut components = (
        node.attribute("component_1").map(str::to_string),
        node.attribute("component_2").map(str::to_string),
    );
    let mut variables = Vec::new();
    for child in children(node, version) {
        match child.tag_name().name() {
            "map_components" => {
                components = (
                    Some(attribute(child, "component_1")?),
                    Some(attribute(child, "component_2")?),
                );
            }
            "map_variables" => variables.push((
                attribute(child, "variable_1")?,
                attribute(child, "variable_2")?,
            )),
            _ => {}
        }
    }
    let (Some(component_1), Some(component_2)) = components else {
        return Err(ReadError::MissingAttribute {
            element: "connection".to_string(),
            attribute: "component_1".to_string(),
        });
    };
    Ok(Connection {
        component_1,
        component_2,
        variables,
    })
}

/// Whether a `<group>` of CellML 1.0 or 1.1 is an encapsulation.
fn is_encapsulation(node: X, version: Version) -> bool {
    children(node, version)
        .filter(|child| child.tag_name().name() == "relationship_ref")
        .any(|child| {
            child.attribute("relationship") == Some("encapsulation")
                || child.attribute((version.namespace(), "relationship")) == Some("encapsulation")
        })
}

/// The `<component_ref>` trees of an encapsulation or of a group.
fn component_refs(node: X, version: Version) -> Result<Vec<ComponentRef>, ReadError> {
    let mut references = Vec::new();
    for child in children(node, version).filter(|c| c.tag_name().name() == "component_ref") {
        references.push(ComponentRef {
            component: attribute(child, "component")?,
            children: component_refs(child, version)?,
        });
    }
    Ok(references)
}

/// An import with the components and the unit definitions it takes.
fn import(node: X, version: Version) -> Result<Import, ReadError> {
    let href = node
        .attribute((XLINK_NS, "href"))
        .or_else(|| node.attribute("href"))
        .map(str::to_string)
        .ok_or_else(|| ReadError::MissingAttribute {
            element: "import".to_string(),
            attribute: "xlink:href".to_string(),
        })?;
    let mut import = Import {
        href,
        components: Vec::new(),
        units: Vec::new(),
    };
    for child in children(node, version) {
        match child.tag_name().name() {
            "component" => import.components.push(ImportedItem {
                name: attribute(child, "name")?,
                reference: attribute(child, "component_ref")?,
            }),
            "units" => import.units.push(ImportedItem {
                name: attribute(child, "name")?,
                reference: attribute(child, "units_ref")?,
            }),
            _ => {}
        }
    }
    Ok(import)
}

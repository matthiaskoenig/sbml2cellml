"""SBML ids of the variables of a CellML model.

libcellml connects variables of different components into equivalence sets,
which the analyser treats as one variable. SBML has one flat id namespace, so
every equivalence set becomes one parameter. The id is the name of the
analyser's representative when no other analyser variable has that name,
otherwise the name is prefixed with the component. Ids are sanitized to SBML
SIds; a sanitized id which is already taken gets a numeric suffix.
"""

import re
from collections import Counter
from typing import Any

import libcellml

#: characters which are not allowed in an SBML SId
SID_INVALID = re.compile(r"[^A-Za-z0-9_]")


def sanitize_id(name: str) -> str:
    """Make a string a valid SBML SId.

    Invalid characters become `_`; a leading digit or an empty string gets a
    `_` prefix.

    Args:
        name: CellML name.

    Returns:
        The SId.
    """
    sid = SID_INVALID.sub("_", name)
    if not sid or not (sid[0].isalpha() or sid[0] == "_"):
        sid = f"_{sid}"
    return sid


def variable_key(variable: Any) -> tuple[str, str]:
    """`(component name, variable name)` of a variable.

    Args:
        variable: libcellml variable with a parent component.

    Returns:
        The key.
    """
    return (variable.parent().name(), variable.name())


def equivalence_set(variable: Any) -> list[Any]:
    """The variable and every variable connected to it, transitively.

    Args:
        variable: libcellml variable.

    Returns:
        The variables of the equivalence set, the given one first.
    """
    seen: dict[tuple[str, str], Any] = {}
    stack = [variable]
    while stack:
        current = stack.pop()
        key = variable_key(current)
        if key in seen:
            continue
        seen[key] = current
        for k in range(current.equivalentVariableCount()):
            stack.append(current.equivalentVariable(k))
    return list(seen.values())


class VariableIds:
    """SBML ids of the variables of an analysed CellML model."""

    def __init__(self, analyser_model: libcellml.AnalyserModel) -> None:
        """Assign the ids.

        Args:
            analyser_model: model of a libcellml analyser without errors.
        """
        self._ids: dict[tuple[str, str], str] = {}
        self._voi: set[tuple[str, str]] = set()

        representatives: list[Any] = []
        voi = analyser_model.voi()
        if voi is not None:
            representatives.append(voi.variable())
        for k in range(analyser_model.stateCount()):
            representatives.append(analyser_model.state(k).variable())
        for k in range(analyser_model.variableCount()):
            representatives.append(analyser_model.variable(k).variable())

        counts = Counter(v.name() for v in representatives)
        used: set[str] = set()
        for representative in representatives:
            name = representative.name()
            if counts[name] > 1:
                name = f"{representative.parent().name()}_{name}"
            sid = sanitize_id(name)
            if sid in used:
                n = 2
                candidate = f"{sid}_{n}"
                while candidate in used:
                    n += 1
                    candidate = f"{sid}_{n}"
                sid = candidate
            used.add(sid)
            for member in equivalence_set(representative):
                self._ids[variable_key(member)] = sid

        if voi is not None:
            for member in equivalence_set(voi.variable()):
                self._voi.add(variable_key(member))

    def lookup(self, component_name: str, variable_name: str) -> str:
        """SBML id of a variable given by component and name.

        Args:
            component_name: name of the component.
            variable_name: name of the variable in that component.

        Returns:
            The SBML id.

        Raises:
            KeyError: if the variable is not part of the analysed model.
        """
        return self._ids[(component_name, variable_name)]

    def id_for(self, variable: Any) -> str:
        """SBML id of a libcellml variable.

        Args:
            variable: libcellml variable with a parent component.

        Returns:
            The SBML id.

        Raises:
            KeyError: if the variable is not part of the analysed model.
        """
        return self._ids[variable_key(variable)]

    def is_voi_key(self, component_name: str, variable_name: str) -> bool:
        """Whether a variable is the variable of integration or equivalent to it."""
        return (component_name, variable_name) in self._voi

    def is_voi(self, variable: Any) -> bool:
        """Whether a libcellml variable is the variable of integration."""
        return variable_key(variable) in self._voi

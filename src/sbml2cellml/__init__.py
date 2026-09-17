"""sbml2cellml - conversion of SBML models to CellML."""

import logging

from sbml2cellml.cellml2sbml import convert_cellml2sbml
from sbml2cellml.sbml2cellml import convert_sbml2cellml

# the package does not configure logging, see `sbml2cellml.log`
logging.getLogger(__name__).addHandler(logging.NullHandler())

__author__ = "Matthias Koenig"
__version__ = "0.1.0"

program_name: str = "sbml2cellml"

__all__ = ["convert_cellml2sbml", "convert_sbml2cellml"]

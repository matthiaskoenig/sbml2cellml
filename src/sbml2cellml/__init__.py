"""sbml2cellml - conversion of SBML models to CellML."""

import logging

# the package does not configure logging, see `sbml2cellml.log`
logging.getLogger(__name__).addHandler(logging.NullHandler())

__author__ = "Matthias Koenig"
__version__ = "0.1.0"

program_name: str = "sbml2cellml"

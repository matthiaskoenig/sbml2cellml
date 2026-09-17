"""Rich console shared by the scripts, examples and the command line."""

from rich import pretty
from rich.console import Console
from rich.theme import Theme

pretty.install()
custom_theme = Theme(
    {
        "success": "green",
        "info": "blue",
        "warning": "orange3",
        "error": "red",
    }
)

#: the console of the package
console = Console(record=True, theme=custom_theme, log_time=False)

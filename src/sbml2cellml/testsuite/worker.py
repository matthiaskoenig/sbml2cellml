"""Simulators in their own processes.

`SimulatorWorker` starts a process (spawn context, so nothing of the parent
is inherited) which runs the functions of `sbml2cellml.testsuite.simulators`
on request. Every call has a timeout; a worker which times out or dies is
replaced, so one bad case never takes the suite down.
"""

import logging
import multiprocessing
from multiprocessing.connection import Connection
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class SimulationFailure(RuntimeError):
    """The simulator raised or the worker died."""


class SimulationTimeout(SimulationFailure):
    """The simulator did not answer within the timeout."""


def _serve(connection: Connection) -> None:
    """Loop of the worker process: run the requested functions."""
    from sbml2cellml.testsuite import simulators

    while True:
        message = connection.recv()
        if message is None:
            break
        function, kwargs = message
        try:
            result = getattr(simulators, function)(**kwargs)
            connection.send({"result": result})
        except Exception as err:
            connection.send({"error": f"{type(err).__name__}: {err}"})


class SimulatorWorker:
    """A simulator running in its own process."""

    def __init__(self, name: str, timeout: float = 60.0) -> None:
        """Create the worker, not started yet.

        Args:
            name: name for the logs, e.g. `roadrunner`.
            timeout: seconds a call may take before the worker is replaced.
        """
        self.name = name
        self.timeout = timeout
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._connection: Connection | None = None

    def start(self) -> None:
        """Start the process."""
        parent, child = self._context.Pipe()
        self._process = self._context.Process(target=_serve, args=(child,), daemon=True)
        self._process.start()
        child.close()
        self._connection = parent
        logger.info("%s worker started (pid %d)", self.name, self._process.pid)

    def stop(self) -> None:
        """Stop the process."""
        if self._process is None:
            return
        try:
            if self._connection is not None and self._process.is_alive():
                self._connection.send(None)
                self._process.join(timeout=5.0)
        except (BrokenPipeError, OSError):
            pass
        if self._process.is_alive():
            self._process.kill()
            self._process.join()
        if self._connection is not None:
            self._connection.close()
        self._process = None
        self._connection = None

    def _restart(self) -> None:
        """Replace a dead or hanging process."""
        logger.warning("%s worker replaced", self.name)
        self.stop()
        self.start()

    def call(self, function: str, **kwargs: Any) -> dict[str, Any]:
        """Run a function of `sbml2cellml.testsuite.simulators` in the worker.

        Args:
            function: name of the function.
            **kwargs: its arguments, picklable.

        Returns:
            The result dictionary of the function.

        Raises:
            SimulationTimeout: if the call exceeds the timeout; the worker is
                replaced.
            SimulationFailure: if the function raised, does not exist, or
                the worker died; a dead worker is replaced.
        """
        if (
            self._connection is None
            or self._process is None
            or not self._process.is_alive()
        ):
            self._restart()
        assert self._connection is not None
        try:
            self._connection.send((function, kwargs))
            if not self._connection.poll(self.timeout):
                self._restart()
                raise SimulationTimeout(
                    f"{self.name}: {function} exceeded {self.timeout} s"
                )
            reply = self._connection.recv()
        except (EOFError, BrokenPipeError, OSError) as err:
            self._restart()
            raise SimulationFailure(
                f"{self.name}: worker died during {function}"
            ) from err
        if "error" in reply:
            raise SimulationFailure(f"{self.name}: {reply['error']}")
        return reply["result"]

    def __enter__(self) -> "SimulatorWorker":
        """Start the worker."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Stop the worker."""
        self.stop()


def frame(result: dict[str, Any]) -> pd.DataFrame:
    """Data frame of a simulator result.

    Args:
        result: `columns` and `rows` as returned by the simulator functions.

    Returns:
        The rows as data frame.
    """
    return pd.DataFrame(result["rows"], columns=result["columns"])

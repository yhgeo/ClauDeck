from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


@dataclass
class TaskResult:
    payload: Any = None


class WorkerSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(TaskResult(result))
        finally:
            self.signals.finished.emit()

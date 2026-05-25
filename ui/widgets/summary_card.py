from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout
from qfluentwidgets import BodyLabel, CardWidget, StrongBodyLabel


class SummaryCard(CardWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title_label = BodyLabel(title, self)
        self.value_label = StrongBodyLabel("0", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

        self.setMinimumWidth(120)
        self.setObjectName("summaryCard")
        self.setStyleSheet(
            """
            SummaryCard#summaryCard {
                background: #ffffff;
                border: 1px solid #cbd8ea;
                border-radius: 12px;
            }
            BodyLabel {
                color: #59687d;
                background: transparent;
            }
            StrongBodyLabel {
                color: #132036;
                background: transparent;
                font-size: 18px;
                font-weight: 700;
            }
            """
        )

    def set_value(self, value: int | str) -> None:
        self.value_label.setText(str(value))

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


class SourceListWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Name", "Kind", "Muted", "Volume"])
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 250)

    def update_sources(self, inputs: dict):
        self.clear()
        for inp in inputs.values():
            item = QTreeWidgetItem([
                inp.input_name,
                inp.input_kind or "input",
                "Muted" if inp.muted else "—",
                f"{inp.volume * 100:.0f}%",
            ])
            if inp.muted:
                item.setForeground(2, self.palette().color(self.foregroundRole()).red())
            self.addTopLevelItem(item)

from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt


class SceneListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.itemClicked.connect(self._on_item_clicked)
        self._on_click: callable = None

    def set_on_click(self, cb: callable):
        self._on_click = cb

    def update_scenes(self, scenes: list[str], current: str):
        current_item = None
        self.clear()
        for name in scenes:
            item = QListWidgetItem(name)
            if name == current:
                item.setBackground(Qt.GlobalColor.highlight)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                current_item = item
            self.addItem(item)
        if current_item:
            self.setCurrentItem(current_item)

    def _on_item_clicked(self, item: QListWidgetItem):
        if self._on_click:
            self._on_click(item.text())

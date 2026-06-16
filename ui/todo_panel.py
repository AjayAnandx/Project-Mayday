from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QComboBox, QLabel, QCheckBox,
    QDialog, QFormLayout, QTextEdit, QSpinBox,
)
from PyQt6.QtCore import Qt

from data_store import get_store


class TodoDialog(QDialog):
    def __init__(self, todo: dict = None, parent=None):
        super().__init__(parent)
        self._todo = todo
        self.setWindowTitle("Edit Todo" if todo else "New Todo")
        self.setMinimumWidth(380)
        self._setup_ui()
        if todo:
            self._populate(todo)

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Todo title")
        layout.addRow("Title:", self.title_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Description (optional)")
        self.desc_edit.setMaximumHeight(80)
        layout.addRow("Description:", self.desc_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["High (1)", "Medium (2)", "Low (3)"])
        layout.addRow("Priority:", self.priority_combo)

        self.due_edit = QLineEdit()
        self.due_edit.setPlaceholderText("YYYY-MM-DD (optional)")
        layout.addRow("Due date:", self.due_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tag1, tag2, ...")
        layout.addRow("Tags:", self.tags_edit)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def _populate(self, todo: dict):
        self.title_edit.setText(todo.get("title", ""))
        self.desc_edit.setText(todo.get("description", ""))
        pri = todo.get("priority", 2)
        self.priority_combo.setCurrentIndex(pri - 1)
        due = todo.get("due_date", "")
        if due:
            self.due_edit.setText(due[:10])
        self.tags_edit.setText(", ".join(todo.get("tags", [])))

    def get_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "priority": self.priority_combo.currentIndex() + 1,
            "due_date": self.due_edit.text().strip() or None,
            "tags": [t.strip() for t in self.tags_edit.text().split(",") if t.strip()],
        }


class TodoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("📋 Todos")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #cdd6f4; padding: 4px 0;")

        filter_layout = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Active", "Completed", "High priority"])
        self.filter_combo.currentTextChanged.connect(self._refresh)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search todos...")
        self.search_edit.textChanged.connect(self._refresh)

        filter_layout.addWidget(self.filter_combo)
        filter_layout.addWidget(self.search_edit)

        self.todo_list = QListWidget()
        self.todo_list.setStyleSheet("""
            QListWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                border-radius: 4px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #313244;
            }
            QListWidget::item:hover {
                background-color: #313244;
            }
        """)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        for b in (self.add_btn, self.edit_btn, self.delete_btn):
            b.setStyleSheet("""
                QPushButton {
                    background-color: #45475a;
                    color: #cdd6f4;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton:hover { background-color: #585b70; }
            """)

        self.add_btn.clicked.connect(self._add)
        self.edit_btn.clicked.connect(self._edit)
        self.delete_btn.clicked.connect(self._delete)

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()

        layout.addWidget(header)
        layout.addLayout(filter_layout)
        layout.addWidget(self.todo_list)
        layout.addLayout(btn_layout)

    def _get_filtered_todos(self):
        store = get_store()
        todos = store.list_todos(True)
        filt = self.filter_combo.currentText()
        query = self.search_edit.text().strip().lower()

        if filt == "Active":
            todos = [t for t in todos if not t["completed"]]
        elif filt == "Completed":
            todos = [t for t in todos if t["completed"]]
        elif filt == "High priority":
            todos = [t for t in todos if t["priority"] == 1]

        if query:
            todos = [t for t in todos if query in t["title"].lower()]

        return todos

    def _refresh(self):
        self.todo_list.clear()
        todos = self._get_filtered_todos()
        for t in todos:
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(4, 2, 4, 2)

            cb = QCheckBox()
            cb.setChecked(t["completed"])
            cb.stateChanged.connect(lambda state, tid=t["id"]: self._toggle(tid, state))

            pri_colors = {1: "#f38ba8", 2: "#f9e2af", 3: "#a6e3a1"}
            color = pri_colors.get(t["priority"], "#cdd6f4")
            label = QLabel(t["title"])
            label.setStyleSheet(f"color: {color}; font-weight: bold;")
            if t["completed"]:
                label.setStyleSheet(f"color: #585b70; font-weight: bold; text-decoration: line-through;")

            info = QLabel("")
            parts = []
            if t.get("due_date"):
                parts.append(f"📅 {t['due_date'][:10]}")
            if t.get("tags"):
                parts.append(f"🏷️ {', '.join(t['tags'])}")
            if parts:
                info.setText(" | ".join(parts))
                info.setStyleSheet("color: #6c7086; font-size: 11px;")

            row.addWidget(cb)
            row.addWidget(label)
            row.addWidget(info)
            row.addStretch()

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            item.setSizeHint(widget.sizeHint())
            self.todo_list.addItem(item)
            self.todo_list.setItemWidget(item, widget)

    def _toggle(self, todo_id: str, state: int):
        store = get_store()
        store.update_todo(todo_id, completed=bool(state))
        self._refresh()

    def _add(self):
        dlg = TodoDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data["title"]:
                store = get_store()
                store.create_todo(**data)
                self._refresh()

    def _edit(self):
        item = self.todo_list.currentItem()
        if not item:
            return
        todo_id = item.data(Qt.ItemDataRole.UserRole)
        store = get_store()
        todo = store.get_todo(todo_id)
        if not todo:
            return
        dlg = TodoDialog(todo, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data["title"]:
                store.update_todo(todo_id, **data)
                self._refresh()

    def _delete(self):
        item = self.todo_list.currentItem()
        if not item:
            return
        todo_id = item.data(Qt.ItemDataRole.UserRole)
        store = get_store()
        store.delete_todo(todo_id)
        self._refresh()

    def refresh(self):
        self._refresh()

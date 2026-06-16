from datetime import datetime, timedelta, date
from calendar import monthrange

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QSizePolicy,
)
from PyQt6.QtCore import Qt

from data_store import get_store


class EventDialog(QDialog):
    def __init__(self, event: dict = None, date_hint: str = None, parent=None):
        super().__init__(parent)
        self._event = event
        self.setWindowTitle("Edit Event" if event else "New Event")
        self.setMinimumWidth(400)
        self._date_hint = date_hint
        self._setup_ui()
        if event:
            self._populate(event)

    def _setup_ui(self):
        layout = QFormLayout(self)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Event title")
        layout.addRow("Title:", self.title_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Description (optional)")
        self.desc_edit.setMaximumHeight(80)
        layout.addRow("Description:", self.desc_edit)

        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("YYYY-MM-DD HH:MM")
        if self._date_hint:
            self.start_edit.setText(f"{self._date_hint} 09:00")
        layout.addRow("Start:", self.start_edit)

        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("YYYY-MM-DD HH:MM")
        if self._date_hint:
            self.end_edit.setText(f"{self._date_hint} 10:00")
        layout.addRow("End:", self.end_edit)

        self.all_day_cb = QCheckBox("All day")
        self.all_day_cb.toggled.connect(self._on_all_day_toggled)
        layout.addRow("", self.all_day_cb)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def _on_all_day_toggled(self, checked: bool):
        if checked and self._date_hint:
            self.start_edit.setText(f"{self._date_hint} 00:00")
            self.end_edit.setText(f"{self._date_hint} 23:59")

    def _populate(self, event: dict):
        self.title_edit.setText(event.get("title", ""))
        self.desc_edit.setText(event.get("description", ""))
        self.start_edit.setText(event.get("start_time", ""))
        self.end_edit.setText(event.get("end_time", ""))
        self.all_day_cb.setChecked(event.get("all_day", False))

    def get_data(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "start_time": self.start_edit.text().strip(),
            "end_time": self.end_edit.text().strip(),
            "all_day": self.all_day_cb.isChecked(),
        }


class CalendarPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = date.today()
        self._setup_ui()
        self._render()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("📅 Calendar")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #cdd6f4; padding: 4px 0;")

        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.next_btn = QPushButton("▶")
        self.today_btn = QPushButton("Today")
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #cdd6f4;")

        for b in (self.prev_btn, self.next_btn, self.today_btn):
            b.setStyleSheet("""
                QPushButton {
                    background-color: #45475a;
                    color: #cdd6f4;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 10px;
                }
                QPushButton:hover { background-color: #585b70; }
            """)

        self.prev_btn.clicked.connect(self._prev_month)
        self.next_btn.clicked.connect(self._next_month)
        self.today_btn.clicked.connect(self._go_today)

        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.month_label)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addWidget(self.today_btn)

        self.grid = QGridLayout()
        self.grid.setSpacing(1)

        layout.addWidget(header)
        layout.addLayout(nav_layout)
        layout.addLayout(self.grid)
        layout.addStretch()

    def _render(self):
        self._clear_grid()
        self.month_label.setText(self._current.strftime("%B %Y"))

        days_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, d in enumerate(days_labels):
            lbl = QLabel(d)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold; padding: 2px;")
            self.grid.addWidget(lbl, 0, i)

        first_day = self._current.replace(day=1)
        start_weekday = first_day.weekday()
        days_in_month = monthrange(self._current.year, self._current.month)[1]

        store = get_store()
        events = store.list_events()

        row = 1
        for day_num in range(1, days_in_month + 1):
            col = (start_weekday + day_num - 1) % 7
            if day_num > 1 and col == 0:
                row += 1

            cell = self._create_day_cell(self._current.year, self._current.month, day_num, events)
            self.grid.addWidget(cell, row, col)

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _create_day_cell(self, year: int, month: int, day_num: int, events: list[dict]) -> QWidget:
        cell = QWidget()
        cell.setStyleSheet("""
            QWidget {
                background-color: #181825;
                border-radius: 4px;
            }
        """)
        cell.setMinimumSize(60, 50)
        cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(cell)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(1)

        is_today = (year, month, day_num) == (date.today().year, date.today().month, date.today().day)
        is_current_month = (year, month) == (self._current.year, self._current.month)

        date_str = f"{year:04d}-{month:02d}-{day_num:02d}"
        day_events = [e for e in events if e.get("start_time", "").startswith(date_str)]

        day_label = QLabel(str(day_num))
        day_label.setStyleSheet(f"""
            font-size: 11px;
            font-weight: bold;
            color: {"#89b4fa" if is_today else "#cdd6f4"};
        """)

        layout.addWidget(day_label)

        for ev in day_events[:2]:
            truncated = ev['title'][:10] + "…" if len(ev['title']) > 10 else ev['title']
            ev_label = QLabel(f"• {truncated}")
            ev_label.setStyleSheet("color: #a6e3a1; font-size: 9px;")
            layout.addWidget(ev_label)

        if len(day_events) > 2:
            more = QLabel(f"+{len(day_events) - 2} more")
            more.setStyleSheet("color: #6c7086; font-size: 9px;")
            layout.addWidget(more)

        layout.addStretch()

        cell.mousePressEvent = lambda e, ds=date_str: self._on_day_click(ds)
        cell.setToolTip(f"{day_num} — {len(day_events)} event(s)"
                        + "\n".join(f"\n• {e['title']}" for e in day_events))

        return cell

    def _on_day_click(self, date_str: str):
        dlg = EventDialog(date_hint=date_str, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data["title"] and data["start_time"] and data["end_time"]:
                store = get_store()
                store.create_event(**data)
                self._render()

    def _prev_month(self):
        self._current = self._current.replace(day=1) - timedelta(days=1)
        self._current = self._current.replace(day=1)
        self._render()

    def _next_month(self):
        self._current = self._current.replace(day=1) + timedelta(days=32)
        self._current = self._current.replace(day=1)
        self._render()

    def _go_today(self):
        self._current = date.today()
        self._render()

    def refresh(self):
        self._render()

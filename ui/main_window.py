from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QLabel, QComboBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction

from ui.assistant_panel import AssistantPanel
from ui.todo_panel import TodoPanel
from ui.calendar_panel import CalendarPanel
from assistant.engine import Engine


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mayday — AI Personal Assistant")
        self.setMinimumSize(1200, 700)
        self._mode = "chat"
        self._engine = Engine()
        self._setup_ui()
        self._connect_signals()
        self._apply_theme()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        toolbar = QHBoxLayout()

        title = QLabel("Mayday")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #89b4fa;")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["💬 Chat", "🎤 Voice"])
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)

        self.conv_label = QLabel("Conversation: New")
        self.conv_label.setStyleSheet("color: #6c7086; font-size: 12px;")

        self.new_conv_btn = QPushButton("+ New")
        self.new_conv_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #585b70; }
        """)
        self.new_conv_btn.clicked.connect(self._new_conversation)

        toolbar.addWidget(title)
        toolbar.addSpacing(20)
        toolbar.addWidget(self.mode_combo)
        toolbar.addSpacing(20)
        toolbar.addWidget(self.conv_label)
        toolbar.addWidget(self.new_conv_btn)
        toolbar.addStretch()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.assistant_panel = AssistantPanel()
        self.todo_panel = TodoPanel()
        self.calendar_panel = CalendarPanel()

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.addWidget(self.todo_panel)
        right_split.addWidget(self.calendar_panel)

        self.splitter.addWidget(self.assistant_panel)
        self.splitter.addWidget(right_split)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        main_layout.addLayout(toolbar)
        main_layout.addWidget(self.splitter)

    def _connect_signals(self):
        self.assistant_panel.message_sent.connect(self._on_user_message)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self._engine.on_text(self._on_engine_text)
        self._engine.on_error(self._on_engine_error)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #11111b;
            }
            QWidget {
                background-color: #11111b;
            }
            QSplitter::handle {
                background-color: #313244;
                width: 2px;
                height: 2px;
            }
            QScrollBar:vertical {
                background-color: #11111b;
                width: 8px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #45475a;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _on_user_message(self, text: str):
        self._engine.process_message(text)
        self.todo_panel.refresh()
        self.calendar_panel.refresh()
        title = self._engine.conv.get_title()
        self.conv_label.setText(f"Conversation: {title[:40]}")

    def _on_engine_text(self, text: str):
        self.assistant_panel.append_text(text)

    def _on_engine_error(self, error: str):
        self.assistant_panel.append_text(f"❌ Error: {error}")

    def _on_mode_changed(self, mode_text: str):
        mode = "voice" if "Voice" in mode_text else "chat"
        self._mode = mode
        self.assistant_panel.set_mode(mode)
        if mode == "voice":
            self.assistant_panel.set_voice_status("🎤 Voice mode — speak to interact")
        else:
            self.assistant_panel.set_voice_status("")

    def _new_conversation(self):
        self._engine.conv.new_conversation()
        self.assistant_panel.clear()
        self.conv_label.setText("Conversation: New")

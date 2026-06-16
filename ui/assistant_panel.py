from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser,
    QLineEdit, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal


class AssistantPanel(QWidget):
    message_sent = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "chat"  # "chat" or "voice"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: none;
                font-size: 13px;
                padding: 8px;
            }
        """)

        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #89b4fa;
            }
        """)
        self.input_field.returnPressed.connect(self._send)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
        """)
        self.send_btn.clicked.connect(self._send)

        self.voice_btn = QPushButton("🎤 Voice")
        self.voice_btn.setCheckable(True)
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
            QPushButton:checked {
                background-color: #f38ba8;
                color: #1e1e2e;
            }
        """)

        self.voice_status = QLabel("")
        self.voice_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self.voice_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.voice_status.setVisible(False)

        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.voice_btn)

        layout.addWidget(self.chat_display)
        layout.addWidget(self.voice_status)
        layout.addLayout(input_layout)

    def _send(self):
        text = self.input_field.text().strip()
        if text:
            self.append_text(f"**You:** {text}", is_user=True)
            self.input_field.clear()
            self.message_sent.emit(text)

    def append_text(self, text: str, is_user: bool = False):
        prefix = "🧑 " if is_user else "🤖 "
        html = f'<p style="margin: 4px 0;">{prefix}{text}</p>'
        self.chat_display.append(html)
        scroll = self.chat_display.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def set_mode(self, mode: str):
        self._mode = mode
        is_voice = mode == "voice"
        self.input_field.setVisible(not is_voice)
        self.send_btn.setVisible(not is_voice)
        self.voice_btn.setChecked(is_voice)
        self.voice_status.setVisible(is_voice)

    def set_voice_status(self, text: str):
        self.voice_status.setText(text)

    def clear(self):
        self.chat_display.clear()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Mayday")
    app.setOrganizationName("Mayday")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

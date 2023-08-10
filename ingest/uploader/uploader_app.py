import sys

from PyQt6.QtWidgets import QApplication

from gui import MainWindow, Widget

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = Widget()
    window = MainWindow(widget)
    window.show()
    sys.exit(app.exec())

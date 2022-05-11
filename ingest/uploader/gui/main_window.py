
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction, QMainWindow

class MainWindow(QMainWindow):
    def __init__(self, widget) -> None:
        super().__init__()
        self.title = 'mitwelten Audio Uploader'
        self.setWindowTitle(self.title)

        self.table_widget = widget
        self.setCentralWidget(widget)

        self.menu = self.menuBar()
        self.file_menu = self.menu.addMenu('File')

        ## Exit QAction
        exit_action = QAction('Exit', self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)

        self.file_menu.addAction(exit_action)

        # Status Bar
        self.status = self.statusBar()
        self.status.showMessage('Mitwelten Audio Uploader')

        # Window dimensions
        geometry = self.screen().availableGeometry()
        self.resize(int(geometry.width() * 0.8), int(geometry.height() * 0.7))

    def closeEvent(self, event):
        self.table_widget.close()
        super(QMainWindow, self).closeEvent(event)


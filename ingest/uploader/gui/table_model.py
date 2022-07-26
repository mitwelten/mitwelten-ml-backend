from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QColor

class CustomTableModel(QAbstractTableModel):
    def __init__(self):
        QAbstractTableModel.__init__(self)
        self.row_count = 0
        self.column_count = 8
        self.files = []

    def load_data(self, data):
        self.removeRows(0, len(self.files))
        self.files = data
        self.insertRows(0, len(self.files))

    def rowCount(self, parent):
        return parent.isValid() if 0 else len(self.files)

    def columnCount(self, parent):
        return parent.isValid() if 0 else 8

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return ('Action', 'Start Date', 'Duration', 'Filesize', 'Samplerate', 'Recording Status', 'Comment', 'Source File Path')[section]
        else:
            return f"{section}"

    def insertRows(self, row, count, parent=QModelIndex()):
        self.beginInsertRows(parent, row, count-1)
        self.endInsertRows()
        return True

    def removeRows(self, row, count, parent=QModelIndex()):
        self.beginRemoveRows(parent, row, count-1)
        self.endRemoveRows()
        return True

    def data(self, index, role=Qt.DisplayRole):
        column = index.column()
        row = index.row()
        data = self.files[row]
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if column == 0:
                if data['duplicate_check'][0] or data['duplicate_check'][1]:
                    state = []
                    if data['duplicate_check'][0]:
                        state.append('duplicate')
                    if data['duplicate_check'][1]:
                        state.append('name collision')
                    return f"skip ({', '.join(state)})"
                else:
                    return 'upload'
            elif column == 1:
                return str(data['time_start'])
            elif column == 2:
                duration = '{:02d}:{:02d}'.format(int(data['duration'] // 60), int(data['duration'] % 60))
                return duration
            elif column == 3:
                filesize = data['filesize'] / (1024**2)
                return f'{filesize:.2f} MiB'
            elif column == 4:
                return str(data['sample_rate'])
            elif column == 5:
                return str(data['rec_end_status'])
            elif column == 6:
                return '' if data['comment'] == None else str(data['comment'])
            elif column == 7:
                return str(data['original_file_path'])
        elif role == Qt.BackgroundRole:
            if data['row_state'] == 1:
                return QColor(Qt.darkGreen)
            if data['duplicate_check'][0] or data['duplicate_check'][1] or data['row_state'] == 0:
                return QColor(Qt.darkRed)
        # elif role == Qt.TextAlignmentRole:
        #     return Qt.AlignLeft
        return None

    def setData(self, index, value, role):
        if role == Qt.EditRole:
            self.files[index.row()]['comment'] = value if value != '' else None
            return True

    def flags(self, index):
        column = index.column()
        if column == 6:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
        else:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable

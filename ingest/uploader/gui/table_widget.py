
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QComboBox, QDialogButtonBox,
    QVBoxLayout, QFileDialog, QVBoxLayout, QLabel, QProgressBar,
    QPushButton, QHeaderView, QSizePolicy, QTableView, QWidget)

import re
import psycopg2 as pg
from psycopg2 import pool

import credentials as crd
from clients import MetaDataReader, UploadClient
from . import CustomTableModel

node_labels = [
    '0000-0000', # undefined
    '0863-3235',
    '1874-8542',
    '2061-6644',
    '2614-9017',
    '3164-8729',
    '3704-8490',
    '3994-7806',
    '4258-6870',
    '4672-2602',
    '6431-2987',
    '6444-8804',
    '8125-0324',
    '8477-2673',
    '9589-1225',
]

class Widget(QWidget):
    def __init__(self):
        QWidget.__init__(self)

        self.dbPool = None
        self.file = ''
        self.node_label = '0000-0000'

        # Getting the Model
        self.model = CustomTableModel()

        # Creating a QTableView
        self.table_view = QTableView()
        self.table_view.setModel(self.model)

        # QTableView Headers
        self.horizontal_header = self.table_view.horizontalHeader()
        self.vertical_header = self.table_view.verticalHeader()
        self.horizontal_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.vertical_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontal_header.setStretchLastSection(True)

        # QWidget Layout
        self.main_layout = QVBoxLayout()
        self.bottom_layout = QVBoxLayout()
        self.selector_layout = QHBoxLayout()

        ## table layout
        size = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        size.setHorizontalStretch(1)
        size.setVerticalStretch(1)
        self.table_view.setSizePolicy(size)

        # select box for node_label
        self.cb = QComboBox()
        self.cb.addItem('0000-0000 (choose node label)')
        self.cb.currentIndexChanged.connect(self.onSelectionChange)
        self.selector_layout.addWidget(QLabel('SD-Card/Node Label:'))
        self.selector_layout.addWidget(self.cb)
        self.selector_layout.addStretch()

        # [group] import button
        self.importButton = QPushButton('Import Metadata',
            clicked = lambda: self.readMeta())
        self.importButton.setEnabled(False)

        # [group] upload button
        self.uploadButton = QPushButton('Upload Audiofiles', self,
            clicked = lambda: self.uploadFiles())
        self.uploadButton.setEnabled(False)

        # [group] of buttons above
        buttonBox = QDialogButtonBox(Qt.Horizontal);
        buttonBox.addButton(self.importButton, QDialogButtonBox.ActionRole)
        buttonBox.addButton(self.uploadButton, QDialogButtonBox.ActionRole)
        self.bottom_layout.addWidget(buttonBox)

        # create status label
        self.statusLabel = QLabel('First, select the SD-Card/Node Label')
        self.bottom_layout.addWidget(self.statusLabel)

        # pbtest
        self.pbar = QProgressBar(self)
        self.bottom_layout.addWidget(self.pbar)

        # assemble layouts
        self.main_layout.addWidget(self.table_view)
        self.main_layout.addStretch()
        self.main_layout.addLayout(self.selector_layout)
        self.main_layout.addLayout(self.bottom_layout)

        # set the layout
        self.setLayout(self.main_layout)

        # fill node selection options
        self.cb.addItems(self.fetchDeployments())

    def onSelectionChange(self):
        self.node_label = re.match(r'(\d{4}-\d{4}).*', self.cb.currentText()).groups()[0]
        print(self.node_label)
        if self.node_label != '0000-0000':
            self.importButton.setEnabled(True)
        else:
            self.importButton.setEnabled(False)

    def onExtractIteration(self, count, path):
        self.pbar.setValue(count)
        self.statusLabel.setText(f'Imported metadata: {path}')

    def onExtractFinished(self, audiofiles):
        self.importButton.setEnabled(True)
        self.statusLabel.setText(f'Built file list of {len(audiofiles)} audiofiles')

        self.model.load_data(audiofiles)
        self.table_view.resizeColumnsToContents()

        self.to_upload = [af for af in audiofiles if af['duplicate_check'][0] == False and af['duplicate_check'][1] == False]
        if len(self.to_upload) > 0:
            self.uploadButton.setEnabled(True)
            self.statusLabel.setText(f'Metadata imported. Next, check if everything is fine and upload the files.')
        else:
            self.uploadButton.setEnabled(False)
            self.statusLabel.setText(f'No valid audiofiles found. Maybe try another folder?')

    def onUploadIteration(self, count, row_id, file_id, etag):
        self.statusLabel.setText(f'Uploaded file with ID {file_id} and etag {etag}')
        # setting value to progress bar
        self.pbar.setValue(count)
        # update the table
        for r in self.to_upload:
            if r['row_id'] == row_id:
                r['row_state'] = 1 if etag else 0
        self.model.layoutChanged.emit()

    def onUploadFinished(self, count):
        self.statusLabel.setText(f'Upload finished: {count}')

    def browseForSource(self):
        self.file = str(QFileDialog.getExistingDirectory(self, 'Browse for source folder'))
        self.statusLabel.setText(f'Source folder set to "{self.file}"')

    def readMeta(self):
        if not self.connectDb():
            return
        if(len(self.file) == 0):
            self.browseForSource()

        self.pbar.setValue(0)
        self.metareader = MetaDataReader(self.dbPool, self.file, self.node_label)
        self.metareader.totalChanged.connect(lambda total: self.pbar.setMaximum(total))
        self.metareader.countChanged.connect(self.onExtractIteration)
        self.metareader.extractFinished.connect(self.onExtractFinished)
        self.metareader.start()
        self.statusLabel.setText(f'Importing metadata...')
        self.importButton.setEnabled(False)

    def uploadFiles(self):
        if not self.connectDb():
            return

        self.pbar.setMaximum(len(self.to_upload))
        self.pbar.setValue(0)
        self.statusLabel.setText(f'Uploading audiofiles...')
        self.uploader = UploadClient(self.dbPool, self.to_upload)
        self.uploader.countChanged.connect(self.onUploadIteration)
        self.uploader.uploadFinished.connect(self.onUploadFinished)
        self.uploader.start()
        self.uploadButton.setEnabled(False)

    def fetchDeployments(self):
        if not self.connectDb():
            return
        db = self.dbPool.getconn()
        cursor = db.cursor()

        cursor.execute(f'''
        select period, d.node_id, n.node_label from {crd.db.schema}.deployments d
        inner join {crd.db.schema}.nodes n on d.node_id = n.node_id
        where n.platform = 'AudioMoth' order by n.node_label
        ''')
        nodes = cursor.fetchall()
        cursor.close()
        self.dbPool.putconn(db)
        node_labels = []
        for n in nodes:
            start = '-inf' if n[0].lower == None else n[0].lower.strftime('%Y-%m-%d')
            end = 'inf' if n[0].upper == None else n[0].upper.strftime('%Y-%m-%d')
            node_labels.append(f'{n[2]} ({start} - {end})')
        return node_labels

    def connectDb(self):
        if self.dbPool == None:
            self.statusLabel.setText(f'Connecting to database server')
            credentials = {
                'host':crd.db.host,
                'port':crd.db.port,
                'database':crd.db.database,
                'user':crd.db.user,
                'password':crd.db.password
            }
            try:
                conn = pg.connect(**credentials)
                conn.close()
            except:
                self.statusLabel.setText(f'Unable to connect to database server. Are you connected to the FHNW network?')
                return False
            else:
                self.dbPool = pool.ThreadedConnectionPool(5, 10, **credentials)
                return True
        else:
            return True

    def close(self):
        if self.dbPool and not self.dbPool.closed:
            self.dbPool.closeall()

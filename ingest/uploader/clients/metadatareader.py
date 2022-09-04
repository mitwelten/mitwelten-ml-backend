import os
import re
import hashlib
import audio_metadata

from datetime import datetime, timezone, timedelta
from os.path import basename, dirname

import mimetypes
from PyQt5.QtCore import QThread, pyqtSignal
from concurrent.futures import ThreadPoolExecutor

import credentials as crd

BS = 65536

rec_nok_str = {
    'microphone change': 'MICROPHONE_CHANGED',
    'change of switch position': 'SWITCH_CHANGED',
    'switch position change': 'SWITCH_CHANGED',
    'low voltage': 'SUPPLY_VOLTAGE_LOW',
    'magnetic switch': 'MAGNETIC_SWITCH',
    'file size limit': 'FILE_SIZE_LIMITED'
}
class MetaDataReader(QThread):

    indexChanged = pyqtSignal(int)
    countChanged = pyqtSignal(int, str)
    totalChanged = pyqtSignal(int)
    extractFinished = pyqtSignal(list)

    def __init__(self, dbConnectionPool, path, node_label, ssd=False):
        QThread.__init__(self)
        self.dbConnectionPool = dbConnectionPool
        self.path = path
        self.node_label = node_label
        self.ssd = ssd

    def run(self):
        audiofiles = []
        textfiles = []
        count = 0
        for root, dirs, files in os.walk(os.fspath(self.path)):
            for file in files:
                filepath = os.path.abspath(os.path.join(root, file))
                try:
                    file_size = os.path.getsize(filepath)
                    file_type = mimetypes.guess_type(filepath)
                    if file_size == 0:
                        raise Exception('File is empty', file, 'empty')
                    elif os.path.basename(filepath).startswith('.'):
                        raise Exception('File is hidden', file, 'hidden')
                    elif file_type[0] == 'text/plain':
                        textfiles.append([filepath])
                    elif file_type[0] == 'application/zip':
                        raise Exception('File is zip archive, please unpack first', file, file_type[0])
                    elif file_type[0] == 'audio/x-wav' or file_type[0] == 'audio/wav':
                        audiofiles.append(filepath)
                        count += 1
                        self.indexChanged.emit(count)
                    else:
                        raise Exception('File format not compatible', file, file_type[0])
                except Exception as e:
                    if(len(e.args)) == 3:
                        print(f'skipping {e.args[1]}: {e.args[0]} ({e.args[2]})')
                    else:
                        print(e)
        # signal main thread: count of files
        self.totalChanged.emit(len(audiofiles))

        db = self.dbConnectionPool.getconn()
        cursor = db.cursor()
        audiofiles_meta = []
        count = 0

        # random read is very slow on hdd, multithreading is actually worse
        # making checkDuplicate multithreaded would probably help a bit
        with ThreadPoolExecutor(os.cpu_count() if self.ssd else 1) as executor:
            for meta in executor.map(self.extract_meta, audiofiles):
                meta['node_label'] = self.node_label
                meta['comment'] = None
                meta['duplicate_check'] = self.checkDuplicate(cursor, meta) # TODO: inline
                meta['row_state'] = -1 # for GUI: -1=no state, 0=OK, 1=error
                meta['row_id'] = count # this is used to identify rows in GUI
                count += 1
                audiofiles_meta.append(meta)
                self.countChanged.emit(count+1, meta['original_file_path'])

        cursor.close()
        self.dbConnectionPool.putconn(db)
        self.extractFinished.emit(audiofiles_meta)

    def is_valid_id(self, arg):
        result = re.search(r'(^\d{4})[-_](\d{4})$', arg).groups()
        if len(result) == 2:
            return f'{result[0]}-{result[1]}'
        else:
            raise ValueError(f'{arg}: Incorrect format for node label (0000-0000)')

    def is_readable_dir(self, arg):
        try:
            if os.path.isfile(arg):
                arg = dirname(arg)
            if os.path.isdir(arg) and os.access(arg, os.R_OK):
                return arg
            else:
                raise f'{arg}: Directory not accessible'
        except Exception as e:
            raise ValueError(f'Can\'t read directory/file {arg}')

    def checkDuplicate(self, cursor, item):
        query = '''
        WITH n AS (
            SELECT %s as sha256,
            %s||'/'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD/HH24/') -- file_path (node_label, time_start)
            || %s||'_'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||%s -- file_name (node_label, time_start, extension)
            as object_name
        )
        SELECT f.sha256 = n.sha256 as hash_match,
            f.object_name = n.object_name as object_name_match
        from {schema}.files_audio f, n
        where (f.sha256 = n.sha256 or f.object_name = n.object_name)
        '''.format(schema=crd.db.schema)
        cursor.execute(query, (item['sha256'], item['node_label'], item['time_start'], item['node_label'], item['time_start'], '.wav'))
        result = cursor.fetchone()
        if result is None:
            result = (False, False)
        return result # duplicate hash, path/file name collision

    def extract_meta(self, path):
        info = {}

        # create SHA256 hash
        file_hash = hashlib.sha256()
        with open(path, 'rb') as f:
            fb = f.read(BS)
            while len(fb) > 0:
                file_hash.update(fb)
                fb = f.read(BS)
        info['sha256'] = file_hash.hexdigest()

        # TODO: find sensible defaults if audiofile doesn't contain AudioMoth Data
        meta = audio_metadata.load(path)
        comment = meta.tags.comment[0]

        info['original_file_path'] = path
        info['filesize'] = meta.filesize
        info['audio_format'] = meta.streaminfo.audio_format
        info['bit_depth'] = meta.streaminfo.bit_depth
        info['channels'] = meta.streaminfo.channels
        info['duration'] = meta.streaminfo.duration
        info['sample_rate'] = meta.streaminfo.sample_rate

        if 'text' in comment:
            comment = comment['text']
        # Read the time and timezone from the header
        ts = re.search(r"(\d\d:\d\d:\d\d \d\d/\d\d/\d\d\d\d)", comment)[1]
        tz = re.search(r"\(UTC([-|+]\d+)?:?(\d\d)?\)", comment)
        hrs = 0 if tz[1] is None else int(tz[1])
        mins = 0 if tz[2] is None else -int(tz[2]) if hrs < 0 else int(tz[2])

        info['serial_number'] = re.search(r"by AudioMoth ([^ ]+)", comment)[1]

        extmic = re.search(r'using external microphone', comment)
        if extmic != None:
            info['source'] = 'external'
        else:
            info['source'] = 'internal'

        info['gain'] = re.search(r"at ([a-z-]+) gain", comment)[1]

        # - Band-pass filter with frequencies of 1.0kHz and 192.0kHz applied.
        # LOW_PASS_FILTER x, BAND_PASS_FILTER x y, HIGH_PASS_FILTER x
        bpf = re.search(r"Band-pass filter with frequencies of (\d+\.\d+)kHz and (\d+\.\d+)kHz applied\.", comment)
        lpf = re.search(r"Low-pass filter with frequency of (\d+\.\d+)kHz applied\.", comment)
        hpf = re.search(r"High-pass filter with frequency of (\d+\.\d+)kHz applied\.", comment)

        if bpf != None:
            info['filter'] = f'BAND_PASS_FILTER {bpf[1]} {bpf[2]}'
        elif lpf != None:
            info['filter'] = f'LOW_PASS_FILTER {lpf[1]}'
        elif hpf != None:
            info['filter'] = f'HIGH_PASS_FILTER {hpf[1]}'
        else:
            info['filter'] = 'NO_FILTER'

        timestamp = datetime.strptime(ts, "%H:%M:%S %d/%m/%Y")
        info['time_start'] = timestamp.replace(tzinfo=timezone(timedelta(hours=hrs, minutes=mins)))

        amp_res = re.search(r'Amplitude threshold was ([^ ]+) with ([^ ]+)s minimum trigger duration\.', comment)
        if amp_res != None:
            info['amp_thresh'], info['amp_trig'] = amp_res.groups()
        else:
            info['amp_thresh'], info['amp_trig'] = None, None # for postgres

        # Read the battery voltage and temperature from the header
        info['battery'] = re.search(r"(\d\.\d)V", comment)[1]
        info['temperature'] = re.search(r"(-?\d+\.\d)C", comment)[1]

        # read the remaining comment:
        #
        # !RECORDING_OKAY and ever only one more condition
        #
        # the AM recordings contain comments from several firmware versions!
        # the syntax differs (see test.py for unit tests of the expression):
        # - [old]     Recording cancelled before completion due to
        # - [...]     Recording stopped due to
        # - [current] Recording stopped
        #
        # MICROPHONE_CHANGED
        # - microphone change.
        # - due to microphone change.
        #
        # SWITCH_CHANGED
        # - change of switch position.
        # - switch position change.
        # - due to switch position change.
        #
        # MAGNETIC_SWITCH
        # - by magnetic switch.
        #
        # SUPPLY_VOLTAGE_LOW
        # - low voltage.
        # - due to low voltage.
        #
        # FILE_SIZE_LIMITED
        # - file size limit.
        # - due to file size limit.
        #
        # - Recording stopped due to switch position change.
        # - Recording cancelled before completion due to low voltage.
        #
        rec_nok = re.search(r" Recording (?:cancelled before completion|stopped) (?:by|due to) (magnetic switch|microphone change|change of switch position|switch position change|low voltage|file size limit)\.", comment)
        if rec_nok != None:
            info['rec_end_status'] = rec_nok_str[rec_nok[1]]
        else:
            info['rec_end_status'] = 'RECORDING_OKAY'

        return info

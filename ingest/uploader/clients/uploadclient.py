from PyQt5.QtCore import QThread, pyqtSignal
import os

import psycopg2 as pg
from psycopg2 import pool

from minio import Minio
from minio.commonconfig import Tags

from concurrent.futures import ThreadPoolExecutor

import credentials as crd

class UploadClient(QThread):

    countChanged = pyqtSignal(int, int, int, str)
    uploadFinished = pyqtSignal(int)

    def __init__(self, dbConnectionPool, fileset):
        QThread.__init__(self)
        self.dbConnectionPool = dbConnectionPool
        self.fileset = fileset

    def run(self):
        count = 0
        CPU_THREADS = os.cpu_count()
        storage = Minio(
            crd.minio.host,
            access_key=crd.minio.access_key,
            secret_key=crd.minio.secret_key,
        )
        bucket_exists = storage.bucket_exists(crd.minio.bucket)
        if not bucket_exists:
            print(f'Bucket {crd.minio.bucket} does not exist.')
            # logger.error(f'Bucket {crd.minio.bucket} does not exist.')
            self.uploadFinished.emit(count)

        def upload_worker(item):

            db = self.dbConnectionPool.getconn()
            cursor = db.cursor()

            # 1. insert record into db
            # 2. get file_id and object_name from insert
            file_id  = None
            object_name  = None
            # 3. upload
            etag = None
            # 4. confirm in db

            try:
                query = '''
                INSERT INTO {schema}.files_audio (
                    object_name,
                    sha256,
                    time,
                    file_size,
                    format,
                    sample_rate,
                    bit_depth,
                    channels,
                    deployment_id,
                    serial_number,
                    battery,
                    temperature,
                    duration,
                    gain,
                    filter,
                    source,
                    rec_end_status,
                    comment,
                    created_at,
                    updated_at)
                VALUES (
                    %s||'/'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD/HH24/') -- file_path (node_label, timestamp)
                    || %s||'_'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||%s, -- file_name (node_label, timestamp, extension)
                    %s, -- sha256
                    %s, -- time
                    %s, -- file_size
                    %s, -- format
                    %s, -- sample_rate
                    %s, -- bit_depth
                    %s, -- channels
                    (SELECT deployment_id from {schema}.deployments where node_id = (SELECT node_id from {schema}.nodes WHERE node_label = %s) and (%s at time zone 'UTC')::timestamptz <@ period), -- deployment_id
                    %s, -- serial_number
                    %s, -- battery
                    %s, -- temperature
                    %s, -- duration
                    %s, -- gain
                    %s, -- filter
                    %s, -- source,
                    %s, -- rec_end_status
                    %s, -- comment
                    CURRENT_TIMESTAMP, -- created_at
                    CURRENT_TIMESTAMP) -- updated_at
                RETURNING file_id, object_name
                '''.format(schema=crd.db.schema)

                cursor.execute(query, (
                    item['node_label'], item['time_start'],
                    item['node_label'], item['time_start'], '.wav',
                    item['sha256'],
                    item['time_start'],
                    item['filesize'],
                    item['audio_format'],
                    item['sample_rate'],
                    item['bit_depth'],
                    item['channels'],
                    item['node_label'],
                    item['time_start'],
                    item['serial_number'],
                    item['battery'],
                    item['temperature'],
                    item['duration'],
                    item['gain'],
                    item['filter'],
                    item['source'],
                    item['rec_end_status'],
                    item['comment']
                ))
                db.commit()
                file_id, object_name = cursor.fetchone()
            except Exception as e:
                print('Error occurred while inserting record for file {}: {}'.format(item['original_file_path'],e))
                # logger.error(f"error occurred for file_id: {file_id}: {exc}")
                return item['row_id'], file_id, etag

            try:
                metadata = { 'file_id': file_id }

                tags = Tags(for_object=True)
                tags['serial_number'] = str(item['serial_number'])
                tags['node_label'] = str(item['node_label'])
                tags['sample_rate'] = str(item['sample_rate'])
                tags['duration'] = str(item['duration'])

                source = item['original_file_path']

                # upload file
                result = storage.fput_object(crd.minio.bucket, object_name, source,
                    content_type='audio/x-wav', metadata=metadata, tags=tags)
                # set upload timestamp
                query = 'UPDATE {schema}.files_audio SET updated_at = CURRENT_TIMESTAMP WHERE file_id = %s'.format(schema=crd.db.schema)
                cursor.execute(query, (file_id,))
                db.commit()
                # report
                # logger.info(f'created {result.object_name}; file_id: {file_id}, etag: {result.etag}')
            except Exception as exc:
                # delete record from db
                query = 'DELETE FROM {schema}.files_audio WHERE file_id = %s'.format(schema=crd.db.schema)
                cursor.execute(query, (file_id,))
                db.commit()
                # report
                # logger.error(f"error occurred for file_id: {file_id}: {exc}")
            finally:
                cursor.close()
                self.dbConnectionPool.putconn(db)
                return item['row_id'], file_id, result.etag

        with ThreadPoolExecutor(CPU_THREADS) as executor:
            count = 0
            for row_id, file_id, etag in executor.map(upload_worker, self.fileset):
                count += 1
                self.countChanged.emit(count, row_id, file_id, etag)
            self.uploadFinished.emit(count)

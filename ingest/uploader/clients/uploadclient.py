from PyQt5.QtCore import QThread, pyqtSignal

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
        CPU_THREADS = 4
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
            # 2. get filename from insert
            file_id  = None
            file_path  = None
            file_name = None
            # 3. upload
            etag = None
            # 4. confirm in db

            try:
                # TODO: add created_at, updated_at
                # TODO: add coordinates
                query = '''
                INSERT INTO files(
                    file_path,
                    file_name,
                    original_file_path,
                    disk,
                    action,
                    state,
                    sha256,
                    time_start,
                    file_size,
                    format,
                    sample_rate,
                    bit_depth,
                    channels,
                    device_id,
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
                    %s||'/'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD/HH24/'), -- file_path (device_id, time_start)
                    %s||'_'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||'.wav', -- file_name (device_id, time_start)
                    %s, -- original_file_path
                    'direct',  -- disk
                    'upload',  -- action
                    'pending', -- state
                    %s, -- sha256
                    %s, -- time_start
                    %s, -- file_size
                    %s, -- format
                    %s, -- sample_rate
                    %s, -- bit_depth
                    %s, -- channels
                    %s, -- device_id
                    %s, -- serial_number
                    %s, -- battery
                    %s, -- temperature
                    %s, -- duration
                    %s, -- gain
                    %s, -- filter
                    %s, -- source,
                    %s, -- rec_end_status
                    %s, -- comment
                    now(), -- created_at
                    now()) -- updated_at
                RETURNING file_id, file_path, file_name
                '''

                cursor.execute(query, (
                    item['device_id'], item['time_start'],
                    item['device_id'], item['time_start'],
                    item['original_file_path'],
                    item['sha256'],
                    item['time_start'],
                    item['filesize'],
                    item['audio_format'],
                    item['sample_rate'],
                    item['bit_depth'],
                    item['channels'],
                    item['device_id'],
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
                file_id, file_path, file_name = cursor.fetchone()
            except Exception as e:
                print('Error occurred while inserting record for file {}: {}'.format(item['original_file_path'],e))
                # logger.error(f"error occurred for file_id: {file_id}: {exc}")
                return item['row_id'], file_id, etag

            try:
                metadata = { 'file_id': file_id }

                tags = Tags(for_object=True)
                tags['serial_number'] = str(item['serial_number'])
                tags['device_id'] = str(item['device_id'])
                tags['sample_rate'] = str(item['sample_rate'])
                tags['duration'] = str(item['duration'])

                source = item['original_file_path']
                target = f'{file_path}{file_name}'

                # upload file
                result = storage.fput_object(crd.minio.bucket, target, source,
                    content_type='audio/x-wav', metadata=metadata, tags=tags)
                # update db: state = 'uploaded', action = null
                query = '''UPDATE files SET action = null, state = 'uploaded', updated_at = now() WHERE file_id = %s'''
                cursor.execute(query, (file_id,))
                db.commit()
                # report
                # logger.info(f'created {result.object_name}; file_id: {file_id}, etag: {result.etag}')
            except Exception as exc:
                # update db: state = 'upload_error'
                query = '''UPDATE files SET state = 'upload_error', updated_at = now() WHERE file_id = %s'''
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

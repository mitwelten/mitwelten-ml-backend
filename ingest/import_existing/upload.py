import sys
import argparse
import logging
from datetime import datetime

import psycopg2 as pg
from psycopg2 import pool

from minio import Minio
from minio.commonconfig import Tags

from tqdm.auto import tqdm
from tqdm.contrib.concurrent import thread_map

sys.path.append('../../')
import credentials as crd

CPU_THREADS = 4
BUCKET = 'ixdm-mitwelten'

dbConnectionPool = None
storage = None
logger = None

source_disk = {
    'mitwelten_hd_small_1': '/Volumes/Elements',
    #'mitwelten_hd_2': '/Volumes/Elements',
    'mitwelten_hd_1': '/Volumes/MITWELTEN'
}

def uploadFile(item):
    file_id, disk, original_file_path, file_path, file_name, sample_rate, device_id, serial_number, temperature, duration, spec_class = item

    db = dbConnectionPool.getconn()
    cursor = db.cursor()

    try:
        metadata = { 'file_id': file_id }

        tags = Tags(for_object=True)
        tags['serial_number'] = str(serial_number)
        tags['device_id'] = str(device_id)
        tags['sample_rate'] = str(sample_rate)
        tags['duration'] = str(duration)
        if spec_class:
            tags['class'] = spec_class

        source = f'{source_disk[disk]}/{original_file_path}'
        target = f'{file_path}{file_name}'

        # upload file
        result = storage.fput_object(BUCKET, target, source,
            content_type='audio/x-wav', metadata=metadata, tags=tags)
        # update db: state = 'uploaded', action = null
        query = '''UPDATE files SET action = null, state = 'uploaded' WHERE file_id = %s'''
        cursor.execute(query, (file_id,))
        db.commit()
        # report
        logger.info(f'created {result.object_name}; file_id: {file_id}, etag: {result.etag}')
    except KeyboardInterrupt:
        cursor.close()
        print('Interrupt requested, what to do now?')
        # sys.exit(0)
    except BaseException as exc:
        # update db: state = 'upload_error'
        query = '''UPDATE files SET state = 'upload_error' WHERE file_id = %s'''
        cursor.execute(query, (file_id,))
        db.commit()
        # report
        # progress.write(f"error occurred for file_id: {file_id}: {exc}")
        logger.error(f"error occurred for file_id: {file_id}: {exc}")
    finally:
        cursor.close()
        dbConnectionPool.putconn(db)

def main():
    parser = argparse.ArgumentParser(description='Upload audiofiles defined in DB to minIO')
    parser.add_argument('--disk', help='disk name selector for files in DB', required=True)
    args = parser.parse_args()

    # file selection criteria
    fileset_query = '''
    select file_id, disk, original_file_path, file_path, file_name,
    sample_rate, device_id, serial_number, temperature, duration, class
    from files
    where (action = 'rename' or state = 'upload_error') and format = '1' and disk = %s
    order by time_start asc
    '''

    # connect to DB
    global dbConnectionPool
    dbConnectionPool = pg.pool.ThreadedConnectionPool(
        5, 20,
        host=crd.db.host,
        port=crd.db.port,
        database=crd.db.database,
        user=crd.db.user,
        password=crd.db.password
    )
    if not dbConnectionPool:
        raise Exception(f'Connection to DB failed (ConnectionPool).')

    # connect to S3 storage
    global storage
    storage = Minio(
        crd.minio.host,
        access_key=crd.minio.access_key,
        secret_key=crd.minio.secret_key,
    )
    bucket_exists = storage.bucket_exists(BUCKET)
    if not bucket_exists:
        raise Exception(f'Bucket {BUCKET} does not exist.')

    # set up logging
    logfilename = '{:%Y-%m-%d_%H-%M-%S}-{}-minio-upload.log'.format(datetime.now(), args.disk)
    print(f'Logging to {logfilename}')
    logging.basicConfig(filemode = 'w', level=logging.INFO,
        filename = logfilename,
        format = '%(levelname)s %(asctime)s - %(message)s')
    global logger
    logger = logging.getLogger()

    db = dbConnectionPool.getconn()
    cursor = db.cursor()
    cursor.execute(fileset_query, (args.disk,))
    fileset = cursor.fetchall()
    cursor.close()
    dbConnectionPool.putconn(db)

    print(f'Starting for {len(fileset)} items.')
    r = thread_map(uploadFile, fileset, max_workers=CPU_THREADS, ascii=True)

    # close connections in pool
    dbConnectionPool.closeall()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Error occurred:', exc)

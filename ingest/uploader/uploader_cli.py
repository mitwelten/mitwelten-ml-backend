import os
import sys
import re
import argparse
import traceback
import pprint
import hashlib
from datetime import datetime, timezone
import logging
import mimetypes

sys.path.append('../../')
import credentials as crd

import psycopg2 as pg
from psycopg2 import pool

from minio import Minio
from minio.commonconfig import Tags

from tqdm.auto import tqdm
from tqdm.contrib.concurrent import thread_map

from PIL import Image, ExifTags

dbConnectionPool = None
storage = None
logger = None

BS = 65536

def image_meta_worker(path, progress):

    # from filename: node_id, timestamp
    # from exif: resolution
    # from os: filesize
    # from file: hash

    meta = {}

    try:
        with Image.open(path) as img:
            img.verify()

        with Image.open(path) as img:
            # cheap transposition to find truncated images
            # consider installing Pillow-SIMD if available for your architecture
            # TODO: put this back in
            img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            meta['resolution'] = img.size

        # create SHA256 hash
        file_hash = hashlib.sha256()
        with open(path, 'rb') as f:
            fb = f.read(BS)
            while len(fb) > 0:
                file_hash.update(fb)
                fb = f.read(BS)
        meta['sha256'] = file_hash.hexdigest()

        meta['file_size'] = os.stat(path).st_size
        meta['file_name'] = os.path.basename(path)
        # 0344-6782_2021-07-03T12-13-46Z.jpg
        fnparts = re.search(r'(\d{4}-\d{4})_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)\.jpe?g', meta['file_name'])
        if fnparts:
            meta['node_id'] = fnparts[1]
            meta['timestamp'] = datetime.strptime(fnparts[2], '%Y-%m-%dT%H-%M-%SZ').replace(tzinfo=timezone.utc)
        else:
            raise ValueError(f"Error parsing filename for node_id and timestamp: {meta['file_name']}", )
    except Exception as e:
        progress.write(f'{path}: {e}')
        meta = None

    return meta

def image_upload_worker(file):
    db = dbConnectionPool.getconn()
    cursor = db.cursor()

    tags = Tags(for_object=True)
    tags['node_id'] = str(file['node_id'])
    query = '''
    INSERT INTO files_image (
        object_name,
        sha256,
        time,
        node_id,
        file_size,
        resolution,
        location)
    VALUES (
        %s||'/'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD/HH24/') -- file_path (node_id, timestamp)
        || %s||'_'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||%s, -- file_name (node_id, timestamp, extension)
        %s, -- sha256
        %s, -- time
        %s, -- node_id
        %s, -- file_size
        %s, -- resolution
        %s) -- location
    ON CONFLICT DO NOTHING
    RETURNING file_id, object_name
    '''
    try:
        cursor.execute(query, (
            file['node_id'],
            file['timestamp'],
            file['node_id'],
            file['timestamp'],
            '.jpg',
            file['sha256'],
            file['timestamp'],
            file['node_id'],
            file['file_size'],
            [int(px) for px in file['resolution']],
            None
        ))
        result = cursor.fetchone()
        file_id, object_name = result
    except:
        logger.error(traceback.format_exc())
        logger.error('rolling back transaction')
        db.rollback()
    else:
        db.commit() # creating record to prevent other running tasks from inserting
        try:
            upload = storage.fput_object(crd.minio.bucket, object_name, file['path'],
                content_type='image/jpeg', metadata={ 'file_id': file_id }, tags=tags)
        except:
            logger.error(traceback.format_exc())
            logger.error('failed uploading: deleting record from db')
            query = 'DELETE FROM files_image WHERE file_id = %s'
            cursor.execute(query, (file_id,))
            db.commit()
        else:
            logger.info(f'created {upload.object_name}; file_id: {file_id}, etag: {upload.etag}')
    finally:
        cursor.close()
        dbConnectionPool.putconn(db)


def build_file_lists(basepath):
    imagefiles = []
    audiofiles = []
    textfiles = []
    print('building file tree...')
    for root, dirs, files in os.walk(os.fspath(basepath)):
        for file in files:
            filepath = os.path.abspath(os.path.join(root, file))
            try:
                file_size = os.path.getsize(filepath) # this might be redundant, does mimetypes depend on it?
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
                elif file_type[0] == 'image/jpeg': # do we need other types to match?
                    imagefiles.append(filepath)
                else:
                    raise Exception('File format not compatible', file, file_type[0])
            except Exception as e:
                if(len(e.args)) == 3:
                    print(f'skipping {e.args[1]}: {e.args[0]} ({e.args[2]})')
                else:
                    print(e)

    print(f'found {len(imagefiles)} image files, {len(audiofiles)} audio files and {len(textfiles)} textfiles')
    return (imagefiles, audiofiles, textfiles)

def extract_image_meta(imagefiles):
    print('extracting metadata for image files...')
    hashtable = {}
    progress = tqdm(total=len(imagefiles))
    for path in imagefiles:
        meta = image_meta_worker(path, progress)
        progress.update(1)
        if not meta: continue
        if meta['sha256'] in hashtable:
            progress.write('duplicate hash in file', hashtable[meta['sha256']]['path'])
            if hashtable[meta['sha256']]['timestamp'] != meta['timestamp']:
                progress.write('timestamp mismatch, please fix')
            progress.write('skipping', path)
        else:
            meta['path'] = path
            hashtable[meta['sha256']] = meta
    progress.close()
    print(f'extracted metadata, found {len(hashtable)} unique image files')
    return hashtable

def check_image_duplicates(imagefiles):
    print('checking for duplicate image files in database...')
    db = dbConnectionPool.getconn()
    cursor = db.cursor()
    query = '''
    WITH n AS (
        SELECT %s as sha256,
        %s||'/'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD/HH24/') -- file_path (device_id, time_start)
        || %s||'_'||to_char(%s at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||%s -- file_name (device_id, time_start, extension)
        as object_name
    )
    SELECT f.sha256 = n.sha256 as hash_match,
        f.object_name = n.object_name as object_name_match
    from files_image f, n
    where (f.sha256 = n.sha256 or f.object_name = n.object_name)
    '''
    upload_list = []
    progress = tqdm(total=len(imagefiles))
    for file in imagefiles.values():
        cursor.execute(query, (
            file['sha256'],
            file['node_id'],
            file['timestamp'],
            file['node_id'],
            file['timestamp'],
            '.jpg'
            ))
        result = cursor.fetchone()
        if result is None:
            upload_list.append(file)
        else:
            state = []
            if result[0]:
                state.append('duplicate')
            if result[1]:
                state.append('name collision')
            progress.write(f"skipping {file['path']}: {', '.join(state)}")
        progress.update(1)
    progress.close()
    cursor.close()
    dbConnectionPool.putconn(db)
    print(f'found {len(upload_list)} image files that don\'t exist in db/storage')
    return upload_list

def is_readable_dir(arg):
    try:
        if os.path.isfile(arg):
            arg = os.path.dirname(arg)
        if os.path.isdir(arg) and os.access(arg, os.R_OK):
            return arg
        else:
            raise f'{arg}: Directory not accessible'
    except Exception as e:
        raise ValueError(f'Can\'t read directory/file {arg}')

def main():
    parser = argparse.ArgumentParser(description='Upload image files to DB and minIO')
    parser.add_argument('--threads', help='number of threads to spawn', default=4)
    parser.add_argument('path', type=lambda x: is_readable_dir(x), help='path to files', nargs=1)
    args = parser.parse_args()

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
    bucket_exists = storage.bucket_exists(crd.minio.bucket)
    if not bucket_exists:
        raise Exception(f'Bucket {crd.minio.bucket} does not exist.')

    # set up logging
    logfilename = '{:%Y-%m-%d_%H-%M-%S}-upload.log'.format(datetime.now())
    print(f'Logging to {logfilename}')
    logging.basicConfig(filemode = 'w', level=logging.INFO,
        filename = logfilename,
        format = '%(levelname)s %(asctime)s - %(message)s')
    global logger
    logger = logging.getLogger()

    # build file tree
    imagefiles, audiofiles, textfiles = build_file_lists(args.path[0])

    # get image metadata and filter duplicates
    imagefiles = extract_image_meta(imagefiles)

    # check image duplicates in DB
    # duplicate check and upload is seperate to preemtivly check for errors
    imagefiles = check_image_duplicates(imagefiles)

    # upload files
    if len(imagefiles) > 0:
        print('uploading files to db and storage...')
        thread_map(image_upload_worker, imagefiles, max_workers=args.threads)
        print('done')

    # close connections in pool
    dbConnectionPool.closeall()

if __name__ == '__main__':
    main()

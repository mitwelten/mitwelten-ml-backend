import hashlib
import logging
import time
import traceback
import argparse
import mimetypes
import os
from pprint import pprint
import re
from datetime import datetime, timezone
import sqlite3
import requests
from multiprocessing.pool import ThreadPool
from queue import Queue, Empty as QueueEmpty

from tqdm.contrib.concurrent import thread_map
from minio import Minio
from minio.commonconfig import Tags
from PIL import Image

import credentials as crd

BS = 65536
APIURL = crd.api.url
# APIURL = 'http://localhost:8000'
COLS = ['file_id', 'sha256', 'path', 'state', 'file_size', 'node_label', 'timestamp', 'resolution_x', 'resolution_y']


class MetadataInsertException(BaseException):
    ...

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

def chunks(lst, n):
    '''Yield successive n-sized chunks from lst.'''
    for i in range(0, len(lst), n):
        yield lst[i:i + n], i

def build_file_lists(basepath):
    imagefiles = []
    if VERBOSE: print('building file tree...')
    for root, dirs, files in os.walk(os.fspath(basepath)):
        for file in files:
            filepath = os.path.abspath(os.path.join(root, file))
            try:
                # file_size = os.path.getsize(filepath) # this might be redundant, does mimetypes depend on it?
                file_type = mimetypes.guess_type(filepath)
                # if file_size == 0:
                #     raise Exception('File is empty', file, 'empty')
                if os.path.basename(filepath).startswith('.'):
                    raise Exception('File is hidden', file, 'hidden')
                elif file_type[0] == 'image/jpeg': # do we need other types to match?
                    imagefiles.append(filepath)
                    if VERBOSE: print(f'{len(imagefiles)}        ', end='\r')
                # else:
                #     raise Exception('File format not compatible', file, file_type[0])
            except Exception as e:
                if(len(e.args)) == 3:
                    print(f'skipping {e.args[1]}: {e.args[0]} ({e.args[2]})')
                else:
                    print(e)

    if VERBOSE: print(f'found {len(imagefiles)} image files')
    return (imagefiles)

def image_meta_worker(row):

    # from filename: node_label, timestamp
    # from exif: resolution
    # from os: filesize
    # from file: hash

    file_id, path = row

    meta = {}

    try:
        with Image.open(path) as img:
            img.verify()

        with Image.open(path) as img:
            # cheap transposition to find truncated images
            # consider installing Pillow-SIMD if available for your architecture
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
            meta['node_label'] = fnparts[1]
            meta['timestamp'] = datetime.strptime(fnparts[2], '%Y-%m-%dT%H-%M-%SZ').replace(tzinfo=timezone.utc)
        else:
            raise ValueError(f"Error parsing filename for node label and timestamp: {meta['file_name']}", )
    except Exception as e:
        print(f'{path}: {e}')
        meta = {}
    finally:
        meta['file_id'] = file_id
        meta['path'] = path
    return meta

def worker(queue: Queue):

    conn = sqlite3.connect('file_index.db')

    while True:

        record = None
        try:
            record = queue.get()
        except KeyboardInterrupt:
            break # ?
        except:
            print('Exiting thread, queue is empty') # ?
            break
        if record == None:
            queue.task_done()
            break

        cur = conn.cursor()

        # connect to S3 storage
        storage = Minio(
            crd.minio.host,
            access_key=crd.minio.access_key,
            secret_key=crd.minio.secret_key,
        )
        bucket_exists = storage.bucket_exists(crd.minio.bucket)
        if not bucket_exists:
            print(f'Bucket {crd.minio.bucket} does not exist.')
            cur.close()
            # TODO: retry in 10 minutes, task is not done
            # TODO: check if other exceptions are raised
            break

        # set up session for REST backend
        api = requests.Session()
        api.auth = (crd.api.username, crd.api.password)
        try:
            r = api.get(f'{APIURL}/login')
            r.raise_for_status()
        except Exception as e:
            print('Connecting to REST backend failed:', str(e))
            cur.close()
            # TODO: retry in 10 minutes, task is not done
            break

        d = record

        # validate record against database
        try:
            r = api.post(f'{APIURL}/validate/image', json={ k: d[k] for k in ('sha256', 'node_label', 'timestamp')})
            validation = r.json()

            if r.status_code != 200:
                raise Exception(f"failed to insert metadata for {d['path']}: {validation['detail']}")

            if validation['hash_match'] or validation['object_name_match']:
                cur.execute('update files set state = -3 where file_id = ?', [d['file_id']])
                conn.commit()
                raise Exception('file exists in database:', d['path'])
            elif validation['node_deployed'] == False:
                cur.execute('update files set state = -6 where file_id = ?', [d['file_id']])
                conn.commit()
                raise Exception('node is not deployed requested time:', d['node_label'], d['timestamp'].isoformat())
            else:
                if VERBOSE: print('new file:', validation['object_name'])
                d['object_name'] = validation['object_name']
                d['node_id']     = validation['node_id']
                d['location_id'] = validation['location_id']

        except Exception as e:
            print('Validation failed:', str(e))
            cur.close()
            queue.task_done()
            continue

        # upload procedure
        try:

            # upload to minio S3
            tags = Tags(for_object=True)
            tags['node_label'] = str(d['node_label'])
            upload = storage.fput_object(crd.minio.bucket, d['object_name'], d['path'],
                content_type='image/jpeg', tags=tags)

            # store upload status
            cur.execute('''
            update files set (state, file_uploaded_at) = (2, strftime('%s'))
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()
            if VERBOSE: print(f'created {upload.object_name}; etag: {upload.etag}')

            # store metadata in postgres
            d['resolution'] = (d['resolution_x'], d['resolution_y'])
            r = api.post(f'{APIURL}/ingest/image',
                json={ k: d[k] for k in ('object_name', 'sha256', 'node_label', 'node_id',
                    'location_id', 'timestamp', 'file_size', 'resolution')})

            if r.status_code != 200:
                raise MetadataInsertException(f"failed to insert metadata for {d['path']}: {r.json()['detail']}")

            # store metadata status
            cur.execute('''
            update files set (state, meta_uploaded_at) = (2, strftime('%s'))
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()
            if VERBOSE: print('inserted metadata into database. done.')

        except MetadataInsertException as e:
            # -5: meta insert error
            print('MetadataInsertException', str(e))
            cur.execute('''
            update files set (state, file_uploaded_at) = (-5, strftime('%s'))
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()
            cur.close()

        except Exception as e:
            # -4: file upload error
            print('File upload error', str(e))
            cur.execute('''
            update files set (state, file_uploaded_at) = (-4, strftime('%s'))
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()
            cur.close()
            # TODO: implement logger
            # logger.error(traceback.format_exc())
            # logger.error('failed uploading: deleting record from db')
            # query = 'DELETE FROM {}.files_image WHERE file_id = %s'.format(crd.db.schema)
        queue.task_done()
    conn.close()

def get_tasks(conn: sqlite3.Connection):
    '''
    yield records marked as 'in progress' (status = 3)
    '''

    while True:
        try:
            c = conn.cursor()
            r = c.execute(f'select {",".join(COLS)} from files where state = 1 limit 1').fetchone()

            d = {}
            if r:
                d = {k: r[i] for (i,k) in enumerate(COLS)}
                c.execute('update files set state = 3 where file_id = ?', [d['file_id']])
                conn.commit()
                c.close()
                yield d
            else:
                c.close()
                print('sleeping...', end='\r')
                time.sleep(10)
        except KeyboardInterrupt:
            c.close()
            raise Exception('KeyboardInterrupt')
        except:
            c.close()
            print(traceback.format_exc(), flush=True)
            raise

def main():
    parser = argparse.ArgumentParser(description='Build file index')
    parser.add_argument('-v', action='store_true', help='print info to stdout')

    parser.add_argument('--index', metavar='PATH', type=lambda x: is_readable_dir(x), help='index files in PATH')
    parser.add_argument('--meta', action='store_true', help='check files and extract and metadata')
    parser.add_argument('--upload', action='store_true', help='upload checked files')
    parser.add_argument('--test', action='store_true', help='select some records')

    parser.add_argument('--threads',  metavar='NTHREADS', help='number of threads to spawn', default=4)
    parser.add_argument('--batchsize', help='number of files to process as batch', default=1024)

    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.v
    NTHREADS = max(1, min(os.cpu_count(), int(args.threads)))
    BATCHSIZE = max(1, min(16384, int(args.batchsize)))

    database = sqlite3.connect('file_index.db')
    c = database.cursor()
    c.execute('''create table if not exists files (
        file_id integer primary key,
        sha256 text unique,
        path text unique not null,
        state integer not null,
        file_size integer,
        node_label text,
        timestamp integer,
        resolution_x integer,
        resolution_y integer,
        indexed_at integer,
        checked_at integer,
        meta_uploaded_at integer,
        file_uploaded_at ingeger
    )''')

    if args.test:
        r = c.execute('select * from files limit 20').fetchall()
        pprint(r)
        database.close()
        return

    if args.index:
        imagefiles = build_file_lists(args.index)
        for batch, i in chunks(imagefiles, BATCHSIZE):
            if VERBOSE: print('\n== processing batch (index)', 1 + (i // BATCHSIZE), 'of', 1 + (len(imagefiles) // BATCHSIZE), ' ==\n')
            c.executemany('''
            insert or ignore into files(path, state, indexed_at)
            values (?, 0, strftime('%s'))
            ''',[(path,) for path in batch])
            database.commit()

    if args.meta:
        records = c.execute('select file_id, path from files where sha256 is null and state = 0').fetchall()

        for batch, i in chunks(records, BATCHSIZE):
            if VERBOSE: print('\n== processing batch (meta)', 1 + (i // BATCHSIZE), 'of', 1 + (len(records) // BATCHSIZE), ' ==\n')
            metalist = thread_map(image_meta_worker, batch, max_workers=NTHREADS)
            if VERBOSE: print('\n== writing batch to database...')
            for meta in metalist:
                try:
                    if len(meta) == 2:
                        raise ValueError
                    c.execute('''
                    update files set (sha256, state, file_size, node_label, timestamp, resolution_x, resolution_y, checked_at)
                    = (?, 1, ?, ?, ?, ?, ?, strftime('%s'))
                    where file_id = ?
                    ''', [meta['sha256'], meta['file_size'], meta['node_label'], meta['timestamp'], meta['resolution'][0], meta['resolution'][1], meta['file_id']])
                except ValueError as e:
                    c.execute('''
                    update files set (state, checked_at) = (-1, strftime('%s'))
                    where file_id = ?
                    ''', [meta['file_id']])
                except sqlite3.IntegrityError as e:
                    print(meta['path'], e)
                    c.execute('''
                    update files set (state, file_size, node_label, timestamp, resolution_x, resolution_y, checked_at)
                    = (-2, ?, ?, ?, ?, ?, strftime('%s'))
                    where file_id = ?
                    ''', [meta['file_size'], meta['node_label'], meta['timestamp'], meta['resolution'][0], meta['resolution'][1], meta['file_id']])
            database.commit()

    if args.upload:

        queue = Queue(maxsize=NTHREADS)

        try:
            pool = ThreadPool(NTHREADS, initializer=worker, initargs=(queue,))

            for task in get_tasks(database):
                queue.put(task)
        except Exception as e:
            print('Exiting queue:', e)

            try:
                while True:
                    task = queue.get(True, 2)
                    print('task from q', task)
                    c.execute('update files set state = 1 where file_id = ?', (task['file_id'],))
            except QueueEmpty:
                database.commit()
            except:
                print(traceback.format_exc(), flush=True)

        finally:
            print('signaling threads to stop...')
            for n in range(NTHREADS):
                queue.put(None)

            print('closing queue...')
            queue.join()

            print('waiting for tasks to end...')
            pool.close()
            pool.join()

            print('done.')

    database.close()

if __name__ == '__main__':
    main()

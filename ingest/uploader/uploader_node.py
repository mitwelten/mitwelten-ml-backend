import hashlib
import signal
import sys
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

from concurrent.futures import ProcessPoolExecutor
from minio import Minio
from minio.commonconfig import Tags
from PIL import Image

import credentials as crd
import uploader_node_config as cfg

BS = 65536
APIURL = crd.api.url
# APIURL = 'http://localhost:8000'
COLS = ['file_id', 'sha256', 'path', 'state', 'file_size', 'node_label', 'timestamp', 'resolution_x', 'resolution_y']


class IndexingException(BaseException):
    ...

class MetadataInsertException(BaseException):
    ...

class ShutdownRequestException(BaseException):
    ...

sig_ctrl = { 'run': True }

def sigterm_handler(signo, stack_frame):
    print('Got signal to stop running:', signo)
    sig_ctrl['run'] = False

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

def build_file_lists(basepath, checkpoint: float = 0):

    imagefiles = []

    for root, dirs, files in os.walk(os.fspath(basepath)):

        # match root to node_id/date/hour
        # skip directories older than checkpoint - 1h
        m = re.match(r'.*/\d{4}-\d{4}/(\d{4}-\d\d-\d\d)/(\d\d)(?:/?|.+)', root)
        if m == None:
            continue
        ts = datetime.strptime('{} {}'.format(*m.groups()), '%Y-%m-%d %H').timestamp()
        if ts < (((checkpoint // 3600) * 3600) - 3600): # round checkpoint to hour of ts
            continue

        # index files
        for file in files:
            filepath = os.path.abspath(os.path.join(root, file))
            if os.stat(os.path.dirname(filepath)).st_mtime < checkpoint:
                break # skip directory if not modified since last checkpoint
            try:
                if os.stat(filepath).st_mtime >= checkpoint:
                    file_type = mimetypes.guess_type(filepath)
                    if os.path.basename(filepath).startswith('.'):
                        continue
                    elif file_type[0] == 'image/jpeg': # do we need other types to match?
                        imagefiles.append(filepath)
                        if VERBOSE: print(f'{len(imagefiles)}        ', end='\r')
            except:
                print(traceback.format_exc())
                # if file is unreadable, exit indexing,
                # avoid updating the checkpoint.
                raise IndexingException

    return imagefiles

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

def store_task_state(conn: sqlite3.Connection, file_id: int, state: int):
    c = conn.cursor()
    c.execute('update files set state = ? where file_id = ?', [state, file_id])
    conn.commit()
    c.close()

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

        # connect to S3 storage
        storage = Minio(crd.minio.host, access_key=crd.minio.access_key, secret_key=crd.minio.secret_key)
        try:
            # the documentation states this would be false if bucked doesn't exist
            # but instead an exception is raised MinioException, code=AccessDenied
            if not storage.bucket_exists(crd.minio.bucket):
                raise RuntimeError(f'Bucket {crd.minio.bucket} does not exist.')
        except Exception as e:
            print('Connecting to S3 bucket failed:', str(e))
            # mark paused
            store_task_state(conn, record['file_id'], 42)
            queue.task_done()
            # wait 10min before running into the same problem with the next task
            time.sleep(600)
            continue

        # set up session for REST backend
        api = requests.Session()
        api.auth = (crd.api.username, crd.api.password)
        try:
            r = api.get(f'{APIURL}/login')
            r.raise_for_status()
        except Exception as e:
            print('Connecting to REST backend failed:', str(e))
            # mark paused
            store_task_state(conn, record['file_id'], 42)
            queue.task_done()
            # wait 10min before running into the same problem with the next task
            time.sleep(600)
            continue

        d = record
        cur = conn.cursor()

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
                raise Exception('node is/was not deployed at requested time:', d['node_label'], d['timestamp'].isoformat())
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

            # delete file from disk, update state
            # record should not be deleted as the hash is used to check for duplicates
            os.remove(d['path'])
            cur.execute('''
            update files set state = 4
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()

        except MetadataInsertException as e:
            # -5: meta insert error
            print('MetadataInsertException', str(e))
            cur.execute('''
            update files set (state, file_uploaded_at) = (-5, strftime('%s'))
            where file_id = ?
            ''', [d['file_id']])
            conn.commit()
            cur.close()

        except FileNotFoundError:
            # -7: file not found error
            # file not found either when uploading or when deleting
            print('Error during upload, file not found: ', d['path'])
            cur.execute('''
            update files set (state, file_uploaded_at) = (-7, strftime('%s'))
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
        file_id = None
        try:
            r = conn.execute(f'select {",".join(COLS)} from files where state = 1 limit 1').fetchone()
            d = {}
            if r:
                d = {k: r[i] for (i,k) in enumerate(COLS)}
                file_id = d['file_id']
                conn.execute('update files set state = 3 where file_id = ?', [file_id])
                conn.commit()
                yield d
            else:
                if VERBOSE: print('sleeping...', end='\r')
                time.sleep(10)
                if not sig_ctrl['run']:
                    break
        except GeneratorExit:
            # reset the last picked up task
            if file_id:
                conn.execute('update files set state = 1 where file_id = ?', [file_id])
                conn.commit()
            break
        except:
            if VERBOSE: print(traceback.format_exc(), flush=True)
            raise

def check_ontime(cfg: cfg.NodeUploaderConfig, timed: bool) -> bool:
    'If current time is in period or no timing is specified run'
    if timed:
        start = datetime.time(datetime.strptime(cfg.period_start, '%H:%M'))
        end   = datetime.time(datetime.strptime(cfg.period_end,   '%H:%M'))
        now   = datetime.time(datetime.now())
        if start > end:
            return now > start or now < end
        else:
            return now > start and now < end
    else:
        return True

def main():
    parser = argparse.ArgumentParser(description='Build file index')
    parser.add_argument('-v', action='store_true', help='print info to stdout')

    parser.add_argument('--index', metavar='PATH', type=lambda x: is_readable_dir(x), help='index files in PATH')
    parser.add_argument('--meta', action='store_true', help='check files and extract and metadata')
    parser.add_argument('--upload', action='store_true', help='upload checked files')
    parser.add_argument('--test', action='store_true', help='select some records')
    parser.add_argument('--resume', action='store_true', help='resume upload for paused tasks')
    parser.add_argument('--pause', action='store_true', help='pause upload for checked tasks')
    parser.add_argument('--retry', action='store_true', help='retry failed uploads')
    parser.add_argument('--move-corrupted', action='store_true', help='move corrupted files to dedicated directory')

    parser.add_argument('--timed', action='store_true', help='only run in configured time period')
    parser.add_argument('--threads', metavar='NTHREADS', help='number of threads to spawn', default=4)
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
    c.execute('create index if not exists files_state_idx on files (state)')
    c.execute('''create table if not exists checkpoints (
        type text unique,
        time_in integer,
        time_out integer
    )''')
    database.commit()

    if args.test:
        r = c.execute('select * from files limit 20').fetchall()
        pprint(r)
        database.close()
        return

    if args.pause:
        r = c.execute('update files set state = 42 where state = 1')
        database.commit()
        database.close()
        return

    if args.resume:
        r = c.execute('update files set state = 1 where state = 42')
        database.commit()
        database.close()
        return

    if args.retry:
        r = c.execute('update files set state = 1 where state in (-4, -5, -6, -7)')
        database.commit()
        database.close()
        return

    if args.index:

        # TODO: make ShutdownRequestException work (use a different handler)
        signal.signal(signal.SIGTERM, sigterm_handler)

        while True:
            try:
                print('indexing')
                checkpoint = c.execute('''select time_out from checkpoints where type = 'index' ''').fetchone()
                checkpoint = 0 if checkpoint == None else checkpoint[0]
                c.execute('''insert into checkpoints(type, time_in) values ('index', strftime('%s'))
                    on conflict(type) do update set time_in = strftime('%s')''')
                database.commit()
                imagefiles = build_file_lists(args.index, checkpoint)
                print(f'adding {len(imagefiles)} image files to index')
                for batch, i in chunks(imagefiles, BATCHSIZE):
                    if VERBOSE: print('\n== processing batch (index)', 1 + (i // BATCHSIZE), 'of', 1 + (len(imagefiles) // BATCHSIZE), ' ==\n')
                    c.executemany('''
                    insert or ignore into files(path, state, indexed_at)
                    values (?, 0, strftime('%s'))
                    ''',[(path,) for path in batch])
                    database.commit()
            except ShutdownRequestException or KeyboardInterrupt:
                break
            except Exception as e:
                # print error but continue
                print(traceback.format_exc())
                time.sleep(900)
            else:
                c.execute('''update checkpoints set time_out = time_in where type = 'index' ''')
                database.commit()
                time.sleep(900)

        database.close()
        sys.exit(0)

    if args.meta:

        # TODO: make ShutdownRequestException work (move loop mechanism to system-d)
        signal.signal(signal.SIGTERM, sigterm_handler)
        nthreads_meta = cfg.meta.threads if cfg.meta.threads else NTHREADS

        while True: # This could be handled in the system unit, restart after exit, with delay
            try:
                # waiting in the beginning gives other jobs time to finish before this one
                time.sleep(600)
                if not check_ontime(cfg.meta, args.timed):
                    continue

                print('extracting metadata, checking for file corruption')
                records = c.execute('select file_id, path from files where sha256 is null and state = 0').fetchall()

                for batch, i in chunks(records, BATCHSIZE):
                    if not check_ontime(cfg.meta, args.timed) or not sig_ctrl['run']:
                        break
                    print(f'processing batch {1 + (i // BATCHSIZE)} of {1 + (len(records) // BATCHSIZE)} ({BATCHSIZE} items)')
                    metalist = []
                    # Using ProcessPool instread of ThreadPool saves a few seconds
                    with ProcessPoolExecutor(nthreads_meta) as executor:
                        metalist = executor.map(image_meta_worker, batch)
                    if VERBOSE: print('\n== writing batch to database...')
                    for meta in metalist:
                        try:
                            if len(meta) == 2:
                                # meta only contains file_id and path == extraction failed
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

            except ShutdownRequestException or KeyboardInterrupt:
                break
            except Exception as e:
                # print error but continue
                print(traceback.format_exc())

        database.close()
        sys.exit(0)

    if args.upload:

        signal.signal(signal.SIGTERM, sigterm_handler)
        signal.signal(signal.SIGINT, sigterm_handler)

        nthreads_upload = cfg.upload.threads if cfg.upload.threads else NTHREADS
        tasks = get_tasks(database)

        while sig_ctrl['run']: # This could be handled in the system unit, restart after exit, with delay
            try:

                # TODO: move to worker. like this it doesn't stop the worker from running
                if not check_ontime(cfg.upload, args.timed):
                    continue

                queue = Queue(maxsize=1)
                pool = ThreadPool(nthreads_upload, initializer=worker, initargs=(queue,))

                for task in tasks:
                    queue.put(task)
                    if not sig_ctrl['run']:
                        raise ShutdownRequestException

            except ShutdownRequestException:
                tasks.close()
                # drain the queue and reset drained tasks
                try:
                    while True:
                        task = queue.get(True, 1)
                        c.execute('update files set state = 1 where file_id = ?', (task['file_id'],))
                        queue.task_done()
                except QueueEmpty:
                    database.commit()
                except:
                    print(traceback.format_exc())

                # close queue and stop worker threads
                if VERBOSE: print('signaling threads to stop...')
                for n in range(nthreads_upload):
                    queue.put(None)

                if VERBOSE: print('closing queue...')
                queue.join()

                if VERBOSE: print('waiting for tasks to end...')
                pool.close()
                pool.join()

                if VERBOSE: print('done.')
                break

            except Exception as e:
                # print error but continue
                print(traceback.format_exc())
                time.sleep(300)

            else:
                if sig_ctrl['run']: time.sleep(300)
                else: break

        database.close()
        sys.exit(0)

    if args.move_corrupted:
        records = c.execute('select file_id, path from files state = -1').fetchall()
        target_dir = '/mnt/elements/corrupted/'
        moved = []

        if records != None:
            try:
                for file_id, path in records:
                    if VERBOSE: print(f'moving ({file_id}) {path} to {target_dir}')
                    shutil.move(path, os.path.join(target_dir,os.path.basename(path)))
                    moved.append([5, file_id])
            except:
                print(traceback.format_exc())

        if len(moved) > 0:
            c.executemany('update files set state = ? where file_id = ?', moved)
            database.commit()

    database.close()

if __name__ == '__main__':
    main()

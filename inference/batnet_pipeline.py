'''
# Detect bat calls in audio files stored on minio storage

1. read a set of object names from the postgres database
2. iterate over the object names
    - download the object from minio storage
    - run bat call detection on the object
    - upload the detection results to postgres database
'''

# patch the SoundFile class to respond with
# a path str to calls of os.path.basename()
def custom_path(self):
    return self.__file_path__

from soundfile import SoundFile
SoundFile.__fspath__ = custom_path

import io
import sys
import time
import traceback
import psycopg2 as pg
from psycopg2 import errors
from minio import Minio

sys.path.append('batnet_pipeline/batdetect2/')
import batdetect2.api as api
from batdetect2.detector.parameters import DEFAULT_MODEL_PATH

sys.path.append('../')
import credentials as crd

def get_tasks():
    db_gen = pg.connect(
        host=crd.db.host,
        port=crd.db.port,
        database=crd.db.database,
        user=crd.db.user,
        password=crd.db.password
    )
    while True:
        try:
            # https://www.postgresql.org/docs/current/explicit-locking.html
            # https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
            cursor = db_gen.cursor()
            cursor.execute(f'''
            update {crd.db.schema}.batnet_tasks
            set state = 1
            where task_id in (
                select task_id from {crd.db.schema}.batnet_tasks
                where state = 0
                for update skip locked
                limit 1
            )
            returning task_id, file_id, config_id;
            ''')
            db_gen.commit()
            task = cursor.fetchone()
            if task:
                yield task
            else:
                print('sleeping...', end='\r')
                time.sleep(10)
        except (errors.OperationalError, errors.InterfaceError) as e:
            print(f'queuing task failed ({str(e)}), retrying.', flush=True)
            # reopen connection, recreate cursor
            db_gen = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        except KeyboardInterrupt:
            break
        except GeneratorExit:
            print('stopping task generator', flush=True)
            break
        except:
            print(traceback.format_exc(), flush=True)
            break
    db_gen.close()

def main():
    db = pg.connect(
        host=crd.db.host,
        port=crd.db.port,
        database=crd.db.database,
        user=crd.db.user,
        password=crd.db.password
    )

    s3 = Minio(
        crd.minio.host,
        access_key=crd.minio.access_key,
        secret_key=crd.minio.secret_key,
    )

    model, params = api.load_model(DEFAULT_MODEL_PATH)
    time_expansion_factor = 1
    detection_threshold = 0.3
    chunk_size = 2
    spec_slices = False

    config = api.get_config(
        **{
            **params,
            "time_expansion": time_expansion_factor,
            "spec_slices": spec_slices,
            "chunk_size": chunk_size,
            "detection_threshold": detection_threshold,
        }
    )

    start_query = f'''
    update {crd.db.schema}.batnet_tasks
    set pickup_on = current_timestamp
    where task_id = %s
    '''

    finish_query = f'''
    update {crd.db.schema}.batnet_tasks
    set state = 2, end_on = current_timestamp
    where task_id = %s
    '''

    cur = db.cursor()

    # iterate over the object names
    for task in get_tasks():
        try:
            # pickup the task and update pickup_on
            task_id, file_id, config_id = task
            cur.execute(start_query, (task_id,))
            db.commit()
            # print(f'starting task id {task_id}, file id {file_id}')

            # get the object name from the database
            cur.execute(f'''
            select object_name from {crd.db.schema}.files_audio
            where file_id = %s;
            ''', (file_id,))
            object_name = cur.fetchone()[0]
            # print(f'got object name {object_name}')

            # download the object from minio storage
            response = s3.get_object(crd.minio.bucket, object_name)
            bytes_buffer = io.BytesIO(response.read())
            audio_file = SoundFile(bytes_buffer)
            audio_file.__file_path__ = str(task_id)
            # audio, samplerate = sf.read(bytes_buffer, dtype='float32')
            # print(f'downloaded {object_name}')

            # run bat call detection on the object
            inference = api.process_file(audio_file, model=model, config=config)
            results = inference['pred_dict']['annotation']
            # print(f'processed {object_name}, {len(results)} results')

            # upload the detection results to postgres database
            if len(results) > 0:
                for r in results:
                    cur.execute(f'''
                        insert into {crd.db.schema}.batnet_results
                        (task_id, file_id, class, event, individual, class_prob, det_prob, start_time, end_time, high_freq, low_freq)
                        values
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    ''', (
                        task_id, file_id,
                        r['class'],
                        r['event'],
                        r['individual'],
                        r['class_prob'],
                        r['det_prob'],
                        r['start_time'],
                        r['end_time'],
                        r['high_freq'],
                        r['low_freq'],
                    ))
            cur.execute(finish_query, (task_id,))
            db.commit()
            print(f'completed {object_name}')
            # api.print_summary(results)
        except:
            print(traceback.format_exc())

    cur.close()
    db.close()

if __name__ == '__main__':
    main()

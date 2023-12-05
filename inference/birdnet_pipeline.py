import sys
import json
import argparse
import traceback
import psycopg2 as pg
from psycopg2 import errors
import multiprocessing as mp
from queue import Empty as QueueEmpty
import time
import os

from birdnet_pipeline.birdnet_batches import batches
from birdnet_pipeline.birdnet_worker import BirdnetWorker

sys.path.append('../')
import credentials as crd

class BirdnetConfig(object):
    def __init__(self):
        self.species_list = {
            'db': 'occurence in (0,1,2,3) and unlikely = false',
            'file': 'species_list.txt',
            'auto': {
                'lon': 7.613764385606163,
                'lat': 47.53774126535403,
                'auto_season': True,
                'loc_filter_thresh': 0.03
            },
        }
        self.overlap = 0
        self.random = {
            'seed': 42,
            'gain': 0.23
        }
        # self.result_type = 'audacity'
        self.model_version = 'BirdNET_GLOBAL_2K_V2.1_Model_FP32'
        # MIN_CONFIDENCE threshold is read from birdnet config.py (0.1)
        # SIGMOID_SENSITIVITY is read from birdnet config.py (1.0)



class Runner(object):
    def __init__(self) -> None:
        self.connect()

    def connect(self):
        self.connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        self.cursor = self.connection.cursor()

    def disconnect(self):
        self.cursor.close()
        self.connection.close()

    def store_config(self, config: BirdnetConfig, comment = None) -> None:
        '''Store config to DB'''
        config_str = json.dumps(config.__dict__, indent=None, skipkeys=True)
        try:
            query = '''
            insert into {}.birdnet_configs(config, comment)
            values (%s, %s)
            returning config_id
            '''.format(crd.db.schema)
            self.cursor.execute(query, (config_str, comment))
            self.connection.commit()
            config_id, = self.cursor.fetchone()
            return config_id
        except pg.errors.UniqueViolation:
            self.connection.rollback()
            self.cursor.execute('''
            select config_id, comment from {}.birdnet_configs
            where config = %s
            '''.format(crd.db.schema), (config_str,))
            config_id, comment = self.cursor.fetchone()
            print(f'Configuration already exists: ID {config_id}, comment "{comment}"')
            return config_id
        except:
            self.connection.rollback()
            print('Error storing configuration to db.')
            raise

    def get_config(self, config_id: int) -> dict:
        '''Read config from DB'''
        query = 'select config from {}.birdnet_configs where config_id = %s'.format(crd.db.schema)
        try:
            self.cursor.execute(query, (config_id,))
            row = self.cursor.fetchone()
            return row[0] # 0 holds the column 'config'
        except:
            print('Error fetching configuration from db.')
            return {}

    def set_default_config(self):
        config = BirdnetConfig()
        config.species_list = {
            'auto': {
                'lon': 7.613764385606163, # merian gardens
                'lat': 47.53774126535403,
                'auto_season': False,     # use inferrend yearly list
                'loc_filter_thresh': 0.03
            }}
        return self.store_config(config, 'default configuration')

    def get_tasks(self):
        # run on dedicated connection
        connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        while True:
            try:
                # https://www.postgresql.org/docs/current/explicit-locking.html
                # https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
                cursor = connection.cursor()
                cursor.execute(f''' -- update {crd.db.schema}.birdnet_tasks
                update {crd.db.schema}.birdnet_tasks
                set state = 1
                where task_id in (
                    select task_id from {crd.db.schema}.birdnet_tasks
                    where state = 0
                    -- order by task_id -- this is very expensive
                    for update skip locked
                    limit 1
                )
                returning task_id, file_id, config_id;
                ''')
                connection.commit()
                task = cursor.fetchone()
                if task:
                    yield task
                else:
                    print('sleeping...', end='\r')
                    time.sleep(10)
            except (errors.OperationalError, errors.InterfaceError) as e:
                print(f'queuing task failed ({str(e)}), retrying.', flush=True)
                # reopen connection, recreate cursor
                connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
            except KeyboardInterrupt:
                break
            except GeneratorExit:
                print('stopping task generator', flush=True)
                break
            except:
                print(traceback.format_exc(), flush=True)
                break
        connection.close()


    def queue_batch(self, config_id, batch_id = 0):
        '''Select a batch of files and insert them as tasks into queue'''
        state = 0
        query = '''
        insert into {}.birdnet_tasks(file_id, config_id, state, scheduled_on, batch_id)
        select file_id, %s, %s, NOW(), %s from ({}) as batch
        on conflict do nothing -- skip duplicate tasks
        '''.format(crd.db.schema, batches[batch_id]['query'])
        self.cursor.execute(query, (config_id, state, batch_id))
        self.connection.commit()
        print(f'added {self.cursor.rowcount} tasks for batch "{batches[batch_id]["comment"]}" to queue')

    def reset_queue(self):
        '''
        Clear pending and failed tasks:
        - Tasks to be kept should throw FK error (results refere to the source task)
        - Only active and completed tasks shoud be kept
        '''
        self.cursor.execute(f'''
        delete from {crd.db.schema}.birdnet_results
            where task_id in (select task_id from {crd.db.schema}.birdnet_tasks where state = 3);
        delete from {crd.db.schema}.birdnet_tasks where state not in (1, 2);
        ''')
        self.connection.commit()

    def reset_failed(self):
        '''
        Set failed tasks back to pending, deleting associated result
        '''
        self.cursor.execute(f'''
        delete from {crd.db.schema}.birdnet_results
            where task_id in (select task_id from {crd.db.schema}.birdnet_tasks where state = 3);
        update {crd.db.schema}.birdnet_tasks set state = 0 where state = 3;
        ''')
        print(f'reset to pending on {self.cursor.rowcount} tasks')
        self.connection.commit()

def worker(queue, localcfg):
    '''Read tasks from queue and process them using BirdnetWorker'''

    connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
    birdnet = BirdnetWorker(connection)

    start_query = f'''
    update {crd.db.schema}.birdnet_tasks
    set pickup_on = now()
    where task_id = %s
    '''

    finish_query = f'''
    update {crd.db.schema}.birdnet_tasks
    set state = %s, end_on = now()
    where task_id = %s
    '''

    while True:
        task = None

        try:
            task = queue.get()
        except KeyboardInterrupt:
            break

        if task == None:
            break

        try:
            connection.cursor().execute(start_query, (task[0],))
            connection.commit()
            birdnet.configure(task[0], localcfg)
            birdnet.load_species_list()
            birdnet.analyse()
        except KeyboardInterrupt:
            # let the task fail.
            # at this point some results may have been written to db,
            # those also may have already been deleted
            connection.cursor().execute(finish_query, (3, task[0],))
            break
        except (errors.OperationalError, errors.InterfaceError) as e:
            print(f'task {task[0]} failed ({str(e)}), retrying.', flush=True)
            # reopen connection, recreate cursor
            connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
            connection.cursor().execute(finish_query, (0, task[0],))
        except:
            print(f'task {task[0]} failed')
            print(traceback.format_exc(), flush=True)
            connection.cursor().execute(finish_query, (3, task[0],))
        else:
            print(f'task {task[0]} succeeded')
            connection.cursor().execute(finish_query, (2, task[0],))
        finally:
            connection.commit()

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

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Run and manage BirdNET inferrence queue')

    p_manage = parser.add_argument_group('Manage Task Queue')
    p_manage.add_argument('--reset-queue', action='store_true', default=False, help='Clear pending and failed tasks')
    p_manage.add_argument('--reset-failed', action='store_true', default=False, help='Reset failed tasks to pending, clearing results')
    p_manage.add_argument('--add-batch', type=int, metavar='ID', help='Queue files defined by batch of ID')

    p_run = parser.add_argument_group('Run Pipeline')
    p_run.add_argument('--run', action='store_true', default=False, help='Work on tasks in queue')
    p_run.add_argument('--tf-gpu', action='store_true', default=False, help='Run on GPU, using protobuf model')
    p_run.add_argument('--source', metavar='PATH', type=lambda x: is_readable_dir(x), help='Read input from disk at PATH instead of S3')

    args = parser.parse_args()

    runner = Runner()

    if args.reset_queue:
        runner.reset_queue()

    if args.reset_failed:
        runner.reset_failed()

    if args.add_batch is not None:
        config_id = runner.set_default_config()
        runner.queue_batch(config_id, args.add_batch)

    if args.run:
        connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        ncpus = 1 if args.tf_gpu else os.cpu_count()
        queue = mp.Queue(maxsize=ncpus)
        localcfg = { 'TF_GPU': args.tf_gpu, 'source_path': args.source }

        try:
            pool = mp.Pool(ncpus, initializer=worker, initargs=(queue, localcfg))

            for task in runner.get_tasks():
                queue.put(task)

        except:
            # anything that is still in queue has not been picked up by workers and can be reset.
            try:
                finish_query = f'''
                update {crd.db.schema}.birdnet_tasks
                set state = 0, pickup_on = null, end_on = null
                where task_id = %s
                '''
                cursor = connection.cursor()
                # reset the task that was already yielded but not yet put into queue
                cursor.execute(finish_query, (task[0],))
                while True:
                    task = queue.get(True, 2)
                    cursor.execute(finish_query, (task[0],))
            except QueueEmpty:
                connection.commit()
            except:
                print(traceback.format_exc(), flush=True)

        finally:
            print('closing queue...')
            queue.close()

            print('waiting for tasks to end...')
            pool.close()
            pool.join()

        print('cleaning up...')
        connection.close()

        print('done.')

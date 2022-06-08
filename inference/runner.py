import sys
import json
import argparse
import psycopg2 as pg
from psycopg2 import errors
import multiprocessing as mp
import time
import os

from birdnet_batches import batches

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
        query = '''
        SELECT file_id
        FROM {}.birdnet_tasks
        WHERE state = 0
        LIMIT 2
        FOR UPDATE SKIP LOCKED
        '''.format(crd.db.schema)
        while True:
            self.cursor.execute(query)
            tasks = self.cursor.fetchall()
            yield tasks
        # https://www.postgresql.org/docs/current/explicit-locking.html
        # https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE
        # https://www.psycopg.org/docs/usage.html#server-side-cursors

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
        - Only active tasks shoud be kept
        '''
        query = f'delete from {crd.db.schema}.birdnet_tasks where state != 1'
        self.cursor.execute(query)
        self.connection.commit()

def gen_tasks():
    for i in range(20):
        print('fetch')
        yield i

# TODO: on KeyboardInterrupt: cancel processing, rollback and set task to state 0
def proc(queue, iolock):
    while True:
        connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        cursor = connection.cursor()
        cursor.execute(f'''
        update {crd.db.schema}.birdnet_tasks
        set state = 1, pickup_on = now()
        where task_id in (
            select task_id from {crd.db.schema}.birdnet_tasks
            where state = 0
            order by task_id
            for update skip locked
            limit 1
        )
        returning task_id, file_id, config_id;
        ''')
        task = cursor.fetchone();
        connection.commit()

        if task == None:
            break

        with iolock:
            print(f'processing {task}...')
        # TODO: wrap birdnet inferrence run in try/except/finally and handle success/error
        time.sleep(2)
        with iolock:
            print(f'done processing {task}')

        cursor.execute('''
        update {}.birdnet_tasks
        set state = 2, end_on = now()
        where task_id = %s
        '''.format(crd.db.schema), (task[0],))
        connection.commit()

if __name__ == '__main__':
    # https://stackoverflow.com/questions/43078980/python-multiprocessing-with-generator
    parser = argparse.ArgumentParser(description='Manage BirdNET tasks')
    parser.add_argument('--reset-queue', action='store_true', default=False, help='Clear pending and failed tasks')
    parser.add_argument('--add-batch', type=int, metavar='ID', help='Queue files defined by batch of ID')
    parser.add_argument('--run', action='store_true', default=False, help='Work on tasks in queue')

    args = parser.parse_args()

    runner = Runner()

    if args.reset_queue:
        runner.reset_queue()

    if args.add_batch is not None:
        config_id = runner.set_default_config()
        runner.queue_batch(config_id, args.add_batch)

    if args.run:
        queue = mp.Queue(maxsize=4)
        iolock = mp.Lock()
        pool = mp.Pool(4, initializer=proc, initargs=(queue, iolock))

        # wrap this in while loop that slowly checks
        # for new stuff in the queue after it runs out of tasks
        for task in range(4):
            queue.put(task)
            with iolock:
                print(f'queued {task}')
        pool.close()
        pool.join()

    # for tasks in runner.get_tasks():
        # ...

    # runner.disconnect()
    # for task in runner.get_tasks():
    #     print(task)
    #     ans = input('continue?')

import sys
import json
import psycopg2 as pg
import multiprocessing as mp
import time
import os

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

    def store_config(self, config: BirdnetConfig) -> None:
        '''Store config to DB'''
        try:
            query = 'insert into {}.birdnet_configs(config) values (%s)'.format(crd.db.schema)
            self.cursor.execute(query, (json.dumps(config.__dict__, indent=None, skipkeys=True),))
            self.connection.commit()
        except:
            self.connection.rollback()
            print('Error storing configuration to db.')

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

    def schedule_tasks(self, config_id):
        self.cursor.execute('''
        -- this is an example query
        insert into {}.birdnet_tasks(file_id, config_id, state, scheduled_on)
        select file_id, %s, %s, NOW() from {}.birdnet_input
        where duration >= 3 and sample_rate = 48000 and node_label = %s
        limit 10
        '''.format(crd.db.schema, crd.db.schema), (config_id, 0, '3704-8490'))
        self.connection.commit()

def gen_tasks():
    for i in range(20):
        print('fetch')
        yield i

def proc(queue, iolock):
    while True:
        connection = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
        cursor = connection.cursor()
        cursor.execute('''
        update {}.birdnet_tasks
        set state = 1, pickup_on = now()
        where task_id in (
            select task_id from tasks
            where state = 0
            order by task_id
            for update skip locked
            limit 1
        )
        returning task_id, file_id, config_id;
        '''.format(crd.db.schema))
        task = cursor.fetchone();
        connection.commit()

        print(task)

        if task == None:
            break

        with iolock:
            print(f'processing {task}...')
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
    runner = Runner()

    queue = mp.Queue(maxsize=4)
    iolock = mp.Lock()
    pool = mp.Pool(4, initializer=proc, initargs=(queue, iolock))

    # wrap this in while loop that slowly checks
    # for new stuff in the queue after it runs out of tasks
    for task in gen_tasks():
        queue.put(task)
        with iolock:
            print(f'queued {task}')

    for _ in range(4):
        queue.put(None)
    pool.close()
    pool.join()

    # for tasks in runner.get_tasks():
        # ...

    # runner.disconnect()
    # for task in runner.get_tasks():
    #     print(task)
    #     ans = input('continue?')

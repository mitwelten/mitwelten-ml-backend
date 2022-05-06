import argparse
from os.path import exists
import psycopg2 as pg
from psycopg2.extras import execute_values

import sys
sys.path.append('../../')
import credentials as crd

def is_readable_file(parser, arg):
  try:
    open(arg, 'r').close()
    return arg
  except IOError:
    raise argparse.ArgumentTypeError(f'Can\'t read file {arg}')

def main():
    parser = argparse.ArgumentParser(description='Insert file paths into DB')
    parser.add_argument('--disk', help='disk name selector for files in DB', required=True)
    parser.add_argument('indexfile', type=lambda x: is_readable_file(parser, x), nargs=1)
    args = parser.parse_args()
    print(args)

    pg_server = pg.connect(
        host=crd.db.host,
        port=crd.db.port,
        database=crd.db.database,
        user=crd.db.user,
        password=crd.db.password
    )
    cursor = pg_server.cursor()
    query = '''INSERT INTO files(original_file_path, disk) VALUES %s'''
    count = 0
    data = []
    with open(args.indexfile[0], 'r') as filelist:
        files = filelist.readlines()
        for file in files:
            filepath = file.strip()
            data.append((filepath, args.disk))
            count += 1
            if count % 1000 == 0:
                print(f'count: {count}, committing 1000 records')
                execute_values(cursor, query, data, template='(%s, %s)', page_size=100)
                pg_server.commit()
                data = []
    print(f'count: {count}, committing remaining records')
    execute_values(cursor, query, data, template=None, page_size=100)
    pg_server.commit()
    cursor.close()
    pg_server.close()

if __name__ == '__main__':
    main()

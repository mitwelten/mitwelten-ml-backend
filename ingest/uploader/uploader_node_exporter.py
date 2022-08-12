import argparse
import asyncio
import os
import sqlite3
import time

import httpx
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile

async def get_response(client, target, timeout):
    try:
        req = await client.get(target['url'], timeout=timeout)
        s = req.status_code
        req.raise_for_status()
    except httpx.RequestError:
        s = None
        t = None
    except Exception as e:
        t = req.elapsed.total_seconds()
    else:
        t = req.elapsed.total_seconds()
    finally:
        return {
            'target': target,
            'elapsed': t,
            'status': s,
        }

def get_mountpoint_state():
    mountpoint = '/mnt/elements'
    '''Check if capture disk is mounted (1: mounted, 0: error)'''
    try:
        if not os.path.ismount(mountpoint):
            raise f'{mountpoint} is not mounted'
        else:
            os.listdir(mountpoint)
    except: return 0
    else: return 1


async def test_http_targets(targets, timeout):
    async with httpx.AsyncClient() as client:
        tasks = [asyncio.ensure_future(get_response(client, target, timeout)) for target in targets]
        return await asyncio.gather(*tasks)

def is_readable_file(arg):
  try:
    file_path = os.path.abspath(arg)
    open(file_path, 'r').close()
    return file_path
  except IOError:
    raise argparse.ArgumentTypeError(f'Can\'t read file {file_path}')

def main():

    parser = argparse.ArgumentParser(description='Mitwelten cam accesspoint - prometheus textfile exporter')
    parser.add_argument('--config-db',    help='Path to AP config sqlite db', type=lambda f: is_readable_file(f), required=True)
    parser.add_argument('--metrics-path', help='Metrics output file path', required=True)
    parser.add_argument('--interval',     help='Gathering inteval in seconds', default='2')
    parser.add_argument('--mountpoint',   help='External HDD mountpoint to check', default='/mnt/elements')
    parser.add_argument('--http-timeout', help='HTTP connection timeout', default=2)
    args = parser.parse_args()

    # check if output can be written
    path = args.metrics_path
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if os.path.isdir(path) and os.access(path, os.W_OK):
        open(args.metrics_path, 'a').close()
    else:
        raise f'Can\'t write to file {args.metrics_path}'

    database = sqlite3.connect(args.config_db)
    c = database.cursor()
    records = c.execute('select id, url, enabled from cameras').fetchall()
    targets = [{'name': r[0], 'url': r[1], 'enabled': r[2]} for r in records]

    registry = CollectorRegistry()
    collectors = {
        'cam_response_latency': Gauge('cam_response_latency', 'HTTP response latency', ['endpoint'], unit='seconds', registry=registry),
        'cam_response_code': Gauge('cam_response_code', 'HTTP response code', ['endpoint'], registry=registry),
        'cam_reachable': Gauge('cam_reachable', 'Cam reachable though HTTP', ['endpoint'], registry=registry),
        'node_mountpoint_state': Gauge('node_mountpoint_state', 'Disk mountpoint state (1: mounted and readable)', registry=registry)
    }

    while True:

        metrics = asyncio.run(test_http_targets(targets, args.http_timeout))
        for m in metrics:
            if m['status'] != None:
                collectors['cam_response_latency'].labels(m['target']['name']).set(m['elapsed'])
                collectors['cam_response_code'].labels(m['target']['name']).set(m['status'])
                collectors['cam_reachable'].labels(m['target']['name']).set(1)
            else:
                collectors['cam_reachable'].labels(m['target']['name']).set(0)

        collectors['node_mountpoint_state'].set(get_mountpoint_state())

        write_to_textfile('./metrics.prom', registry)
        time.sleep(5)

if __name__ == '__main__':
    main()

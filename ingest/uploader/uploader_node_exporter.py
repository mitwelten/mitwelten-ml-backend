import argparse
import asyncio
import os
import sqlite3
import time

import httpx
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile
import RPi.GPIO as GPIO
import board
import adafruit_dht

# GPIO pins connecting to DHT sensor
DHT_VCC_PIN = 26
'GPIO VCC (3.3V)'
DHT_DATA_PIN = 19
'GPIO DHT22 (Data)'

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

def get_temp_humi():
    temp = None
    humi = None
    retry = 0
    dhtDevice = adafruit_dht.DHT22(board.D19, use_pulseio=False)
    while True:
        try:
            temp = dhtDevice.temperature
            humi = dhtDevice.humidity
            break
        except:
            if retry > 2:
                break
            time.sleep(0.05)
            retry += 1
            continue
    dhtDevice.exit()
    return (temp, humi)

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
    parser.add_argument('--report-dht',   help='Report temperature/humidity from DHT sensor', action='store_true')
    args = parser.parse_args()

    # check if output can be written
    if os.access(os.path.dirname(args.metrics_path), os.W_OK):
        open(args.metrics_path, 'a').close()
    else:
        raise Exception(f'Can\'t write to file {args.metrics_path}')

    database = sqlite3.connect(args.config_db)

    registry = CollectorRegistry()
    collectors = {
        'cam_response_latency': Gauge('cam_response_latency', 'HTTP response latency', ['endpoint'], unit='seconds', registry=registry),
        'cam_response_code': Gauge('cam_response_code', 'HTTP response code', ['endpoint'], registry=registry),
        'cam_reachable': Gauge('cam_reachable', 'Cam reachable though HTTP', ['endpoint'], registry=registry),
        'node_mountpoint_state': Gauge('node_mountpoint_state', 'Disk mountpoint state (1: mounted and readable)', registry=registry)
    }

    if args.report_dht:
        collectors['node_env_temp_celsius'] = Gauge('node_env_temp_celsius', 'Environment temperature inside enclosure', registry=registry)
        collectors['node_env_humid_percent'] = Gauge('node_env_humid_percent', 'Environment humidity inside enclosure', registry=registry)
        # set up gpio for dht sensor
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(DHT_VCC_PIN, GPIO.OUT)
        GPIO.output(DHT_VCC_PIN, GPIO.HIGH)
        GPIO.setup(DHT_DATA_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    while True:

        records = database.execute('select id, url, enabled, status_code from cameras').fetchall()
        targets = [{'name': r[0], 'url': r[1], 'enabled': r[2], 'status': r[3]} for r in records]
        http_metrics = asyncio.run(test_http_targets(targets, args.http_timeout))
        for m in http_metrics:
            if m['status'] != None:
                collectors['cam_response_latency'].labels(m['target']['name']).set(m['elapsed'])
                collectors['cam_response_code'].labels(m['target']['name']).set(m['target']['status'])
                collectors['cam_reachable'].labels(m['target']['name']).set(1)
            else:
                collectors['cam_reachable'].labels(m['target']['name']).set(0)

        collectors['node_mountpoint_state'].set(get_mountpoint_state())

        if args.report_dht:
            env_metrics = get_temp_humi()
            if env_metrics[0]: collectors['node_env_temp_celsius'].set(env_metrics[0])
            if env_metrics[1]: collectors['node_env_humid_percent'].set(env_metrics[1])

        write_to_textfile(args.metrics_path, registry)
        time.sleep(5)

if __name__ == '__main__':
    main()

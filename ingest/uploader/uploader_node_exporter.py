from prometheus_client import start_http_server, Summary, Enum
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY
# from typing import Dict
import time
import os

# Create a metric to track time spent and requests made.
REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')

class CustomCollector(object):

    mountpoint = '/mnt/elements'

    @REQUEST_TIME.time()
    def collect(self):
        yield GaugeMetricFamily('node_cpu_temp', 'CPU temperature', value=self.read_cpu_temp(), unit='celsius')
        yield GaugeMetricFamily('node_fan_state', 'Cooling fan state', value=self.read_fan_state())
        yield GaugeMetricFamily('node_mountpoint_state', 'Disk mountpoint state (1: mounted and readable)', value=self.read_mountpoint_state())

        # fp = CounterMetricFamily('node_img_file_processing', 'File processing state gauges')
        # fp.add_metric(['indexed'], 0)
        # fp.add_metric(['error', 'corrupted'], 0)
        # fp.add_metric(['error', 'duplicate_local'], 0)
        # fp.add_metric(['error', 'duplicate_remote'], 0)
        # fp.add_metric(['error', 'upload_error'], 0)
        # fp.add_metric(['error', 'metadata_insert_error'], 0)
        # fp.add_metric(['error', 'deployment_error'], 0)
        # fp.add_metric(['error', 'file_read_error'], 0)
        # fp.add_metric(['checked'], 0)
        # fp.add_metric(['uploaded'], 0)
        # fp.add_metric(['scheduled'], 0)
        # fp.add_metric(['deleted'], 0)
        # fp.add_metric(['corrupted', 'moved'], 0)
        # fp.add_metric(['paused'], 0)
        # yield fp

    def read_cpu_temp(self) -> float:
        '''Read CPU temperature in degrees Celsius'''
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return int(f.read()) / 1000.

    def read_fan_state(self) -> int: # Dict[str, bool]
        '''Check if gpio fan is running'''
        with open('/sys/class/thermal/thermal_zone0/cdev0/cur_state', 'r') as f:
            # running = bool(int(f.read()))
            # states = { 'running': running, 'stopped': not running }
            # return states
            return int(f.read())

    def read_mountpoint_state(self) -> int: # Dict[str, bool]
        '''Check if capture disk is mounted (1: mounted, 0: error)'''
        # states = { 'mounted': False, 'error': False }
        try:
            if not os.path.ismount(self.mountpoint):
                raise f'{self.mountpoint} is not mounted'
            else:
                # try to read from disk
                os.listdir(self.mountpoint)
        except:
            # states['error'] = True
            return 0
        else:
            # states['mounted'] = True
            return 1
        # finally:
        #     return states

REGISTRY.register(CustomCollector())

if __name__ == '__main__':
    # Start up the server to expose the metrics.
    start_http_server(9958)

    # collect metrics
    while True:
        try:
            REGISTRY.collect()
        except Exception as exc:
            print(exc)
        time.sleep(10)

# BirdNET worker layout
# - configure environment with options from BirdnetConfig
# - birdnet loading sequence
# - analyze file

import sys
import os
import re

from inference.birdnet.config import MIN_CONFIDENCE

sys.path.append('birdnet')
import config as cfg
# import model

sys.path.append('../')
import credentials as crd

import lib.audio as audio
from birdnet.analyze import loadCodes, loadLabels, predictSpeciesList, loadSpeciesList

SCHEMA = crd.db.schema

class BirdnetWorker(object):

    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.cursor()

        self.task_id = None
        self.file_id = None
        self.object_name = None
        self.week = None
        self.timestamp = None
        self.config = None

    def __del__(self):
        self.cursor.close()

    def configure(self, task_id):
        self.task_id = task_id
        self.cursor.execute(f'''
        select t.file_id, i.object_name, i.time, c.config,
        floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
        from {SCHEMA}.birdnet_tasks t
        left join {SCHEMA}.birdnet_configs c on c.config_id = t.config_id
        left join {SCHEMA}.birdnet_input i on i.file_id = t.file_id
        where t.task_id = %s
        ''', (self.task_id,))
        self.file_id, self.object_name, self.timestamp, self.config, self.week = self.cursor.fetchone()

        match = re.search(r'(.*)_(V[0-9\.]+)_(.*)', self.config['model_version'])
        if match:
            parts = match.groups()
            model_begin = parts[0] # BirdNET_GLOBAL_2K
            model_version_short = parts[1] # V2.1
            model_end = parts[2] # Model_FP32
            cfg.MODEL_PATH = f"checkpoints/{model_version_short}/{self.config['model_version']}.tflite"
            cfg.MDATA_MODEL_PATH = f"checkpoints/{model_version_short}/{model_begin}_{model_version_short}_MData_{model_end}.tflite"
            cfg.LABELS_FILE = f"checkpoints/{model_version_short}/{model_begin}_{model_version_short}_Labels.txt"
        else:
            raise ValueError()

        cfg.MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.MODEL_PATH)
        cfg.LABELS_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.LABELS_FILE)
        cfg.MDATA_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.MDATA_MODEL_PATH)
        cfg.CODES_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.CODES_FILE)

        # error loggin handled elsewhere
        cfg.ERROR_LOG_FILE = None

        # Load eBird codes, labels
        cfg.CODES = loadCodes()
        cfg.LABELS = loadLabels(cfg.LABELS_FILE)

        # No translated labels
        cfg.TRANSLATED_LABELS = cfg.LABELS

        # Set overlap
        cfg.SIG_OVERLAP = max(0.0, min(2.9, float(self.config['overlap'])))

    def load_species_list(self):
        if 'auto' in self.config['species_list']:
            # predict
            params = self.config['species_list']['auto']
            cfg.LATITUDE  = params['lat']
            cfg.LONGITUDE = params['lon']
            cfg.LOCATION_FILTER_THRESHOLD = params['loc_filter_thresh']

            # hrs = 0 if tz[1] is None else int(tz[1])
            cfg.WEEK = self.week if params['auto_season'] else -1
            predictSpeciesList()
        elif 'db' in self.config['species_list']:
            # load from database
            ...
        else:
            # load from file
            cfg.SPECIES_LIST_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), self.config['species_list']['file'])
            cfg.SPECIES_LIST = loadSpeciesList(cfg.SPECIES_LIST_FILE)

    def analyse(self):
        print(cfg)

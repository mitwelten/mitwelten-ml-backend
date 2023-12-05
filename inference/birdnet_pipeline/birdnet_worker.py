# BirdNET worker layout
# - configure environment with options from BirdnetConfig
# - birdnet loading sequence
# - analyze file

import sys
import os
import re
import tempfile

from minio import Minio
import soundfile as sf
import numpy as np
from psycopg2.extras import execute_values

import config as cfg
import model

import credentials as crd

from .lib import audio
from .birdnet.analyze import loadCodes, loadLabels, predictSpeciesList, loadSpeciesList

SCHEMA = crd.db.schema
PDEBUG = False

class BirdnetWorker(object):

    def __init__(self, connection):
        self.connection = connection

        self.task_id = None
        self.file_id = None
        self.object_name = None
        self.week = None
        self.timestamp = None
        self.config = None
        self.source_path = None

        cfg.CODES_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.CODES_FILE)

    def configure(self, task_id, localcfg):
        self.task_id = task_id
        self.source_path = localcfg['source_path']
        cursor = self.connection.cursor()
        cursor.execute(f'''
        select t.file_id, i.object_name, i.time, c.config,
        floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
        from {SCHEMA}.birdnet_tasks t
        left join {SCHEMA}.birdnet_configs c on c.config_id = t.config_id
        left join {SCHEMA}.birdnet_input i on i.file_id = t.file_id
        where t.task_id = %s
        ''', (self.task_id,))
        self.file_id, self.object_name, self.timestamp, self.config, self.week = cursor.fetchone()

        # db config format:     BirdNET_GLOBAL_2K_V2.1_Model_FP32
        # protobuf (tf gpu):    checkpoints/V2.1/BirdNET_GLOBAL_2K_V2.1_Model
        # tflite (cpu):         checkpoints/V2.1/BirdNET_GLOBAL_2K_V2.1_Model_FP32.tflite
        match = re.search(r'(.*)_(V[0-9\.]+)_(.*)', self.config['model_version'])
        if match:
            parts = match.groups()
            model_begin = parts[0] # BirdNET_GLOBAL_2K
            model_version_short = parts[1] # V2.1
            # since model version 2.2, the tflite mdata model is FP16
            mdata_name = 'MData_Model_FP16' if float(model_version_short[1:]) >= 2.2 else f'MData_{parts[2]}' # Model_FP32
            MDATA_MODEL_PATH = f"checkpoints/{model_version_short}/{model_begin}_{model_version_short}_{mdata_name}.tflite"
            LABELS_FILE = f"checkpoints/{model_version_short}/{model_begin}_{model_version_short}_Labels.txt"
            MODEL_PATH = f"checkpoints/{model_version_short}/{self.config['model_version']}.tflite"
            CODES_FILE = 'eBird_taxonomy_codes_2021E.json' # path needs to be resolved relatively
            if localcfg['TF_GPU']: # cli flag for the runner to choose between tflite and protobuf model
                MODEL_PATH = f"checkpoints/{model_version_short}/{model_begin}_{model_version_short}_Model"

            current_dir = os.path.dirname(os.path.abspath(__file__))
            cfg.MODEL_PATH = os.path.join(current_dir, 'birdnet', MODEL_PATH)
            cfg.LABELS_FILE = os.path.join(current_dir, 'birdnet', LABELS_FILE)
            cfg.MDATA_MODEL_PATH = os.path.join(current_dir, 'birdnet', MDATA_MODEL_PATH)
            cfg.CODES_FILE = os.path.join(current_dir, 'birdnet', CODES_FILE)

            # porential cfg isolation issues:
            # cfg.MODEL_PATH (import, loadModel() etc.)
            # cfg.TFLITE_THREADS (loadModel(), loadMetaModel())
            # cfg.MDATA_MODEL_PATH (loadMetaModel())
            # cfg.LOCATION_FILTER_THRESHOLD (explore())
            # cfg.LABELS (explore())

        else:
            raise ValueError()


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
        # TODO: make sure that cfg is isolated between processes
        # (with 3 tasks it's already confirmed to be isolated)
        temp_dir = tempfile.TemporaryDirectory()
        file = None

        try:
            start, end = 0, cfg.SIG_LENGTH
            results = {}
            samples = []
            timestamps = []

            file = None
            if self.source_path == None:
                client = Minio(
                    crd.minio.host,
                    access_key=crd.minio.access_key,
                    secret_key=crd.minio.secret_key,
                )
                # TODO: load directly to numpy array
                tmppath = os.path.join(temp_dir.name, os.path.basename(self.object_name))
                client.fget_object(crd.minio.bucket, self.object_name, tmppath)
                file = sf.SoundFile(tmppath)
            else:
                file = sf.SoundFile(os.path.join(self.source_path, self.object_name))


            block_size = int(cfg.SIG_LENGTH * cfg.SAMPLE_RATE)
            overlap_seek = int(-cfg.SIG_OVERLAP * cfg.SAMPLE_RATE)
            last_block = False
            block_count = 0

            while file.tell() < file.frames:
                block_count += 1
                if PDEBUG: print('--begin analysis loop. currently at {:.2f}% ({}s, block {})'.format(file.tell() / file.frames * 100., start, block_count), end='\n')

                if (file.tell() + block_size) > file.frames:
                    # remaining samples < block size, pad with noise
                    l = file.frames - file.tell()
                    split = file.read(l)
                    sig = np.hstack((split, audio.noise(split, (block_size - len(split)), 0.23)))
                    last_block = True
                else:
                    # read samples from file
                    sig = file.read(block_size)
                    if file.tell() == file.frames:
                        last_block = True

                # Add to batch
                samples.append(sig)
                timestamps.append([start, end])

                # Advance start and end
                start += cfg.SIG_LENGTH - cfg.SIG_OVERLAP
                end = start + cfg.SIG_LENGTH

                # Check if batch is full or last block
                if len(samples) < cfg.BATCH_SIZE and not last_block:
                    continue

                # Predict
                data = np.array(samples, dtype='float32')
                prediction = model.predict(data)

                # Logits or sigmoid activations?
                if cfg.APPLY_SIGMOID:
                    prediction = model.flat_sigmoid(np.array(prediction), sensitivity=-cfg.SIGMOID_SENSITIVITY)

                # Add to results
                for i in range(len(samples)):

                    # Get timestamp
                    s_start, s_end = timestamps[i]

                    # Get prediction
                    pred = prediction[i]

                    # Assign scores to labels
                    p_labels = dict(zip(cfg.LABELS, pred))

                    # Store results
                    results[str(s_start) + '-' + str(s_end)] = p_labels.items()

                # store and clear results after a fixed number of blocks or last block
                # 1200: fits 60min of (non-overlapping) blocks in one go
                if block_count % 1200 == 0 or last_block:
                    if PDEBUG: print(f'storing results at block {block_count}')
                    if PDEBUG: print('storing results for', self.object_name)
                    self.saveResultsToDb(results)
                    results = {}
                # Clear batch
                samples = []
                timestamps = []
        except:
            # delete results from db
            print(f'error/interrupt occurred during prediction, deleting results for task {self.task_id}')
            self.connection.cursor().execute(f'delete from {SCHEMA}.birdnet_results where task_id = %s', (self.task_id,))
            self.connection.commit()
            raise
        finally:
            file.close()
            temp_dir.cleanup()

    def saveResultsToDb(self, results):
        insert_query = f'''
        insert into {SCHEMA}.birdnet_results
        (task_id, file_id, time_start, time_end, confidence, species)
        values %s
        '''
        data = []
        if PDEBUG: print('count of results:', len(results))
        for timestamp in sorted(results):
            for c in results[timestamp]:
                start, end = timestamp.split('-')
                if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                    label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                    data.append((
                        self.task_id,
                        self.file_id,
                        float(start),
                        float(end),
                        float(c[1]),
                        label.split('_')[0]))
        if PDEBUG: print('count of results after filtering:', len(data))
        try:
            execute_values(self.connection.cursor(), insert_query, data, template=None, page_size=100)
            self.connection.commit()
        except:
            self.connection.rollback()
            raise

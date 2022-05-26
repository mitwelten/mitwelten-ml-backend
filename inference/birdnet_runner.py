import os
import sys
import json
import operator
import argparse
import datetime
import traceback
import tempfile

from multiprocessing import Pool, freeze_support

import psycopg2 as pg
from psycopg2.extras import execute_values
from minio import Minio
import soundfile as sf
import numpy as np

sys.path.append('birdnet')
import config as cfg
import model

sys.path.append('../')
import credentials as crd
import lib.audio as audio

# for now, use manual id.
# don't forget to change it between datasets
# another option: int(datetime.datetime.now().timestamp())
SELECTION_ID = 6
PDEBUG = False

def clearErrorLog():

    if os.path.isfile(cfg.ERROR_LOG_FILE):
        os.remove(cfg.ERROR_LOG_FILE)

def writeErrorLog(msg):

    with open(cfg.ERROR_LOG_FILE, 'a') as elog:
        elog.write(msg + '\n')

def loadFileSet():

    # SELECTION_ID 1
    fileset_query = '''
    select file_id, file_path
    from input_files
    where device_id = '6444-8804'
    order by time_start asc
    '''

    # SELECTION_ID 2
    fileset_query = '''
    select file_id, file_path
    from input_files
    where device_id = '4258-6870' and duration >= 3
    order by time_start asc
    '''

    # SELECTION_ID 3
    fileset_query = '''
    select file_id, file_path
    from input_files
    where device_id ~ 'AM[12]' and duration >= 3
    order by time_start asc
    '''

    # SELECTION_ID 3a (with less threads, fixing the out of memory tasks)
    fileset_query = '''
    select file_id, file_path
    from input_files
    where device_id ~ 'AM[12]' and duration >= 3 and not exists (
        select from results where object_name = file_path
    )
    order by time_start asc
    '''

    # SELECTION_ID 3b (less threads, only files smaller than 1100MB)
    fileset_query = '''
    select file_id, file_path
    from input_files
    where device_id ~ 'AM[12]' and duration >= 3 and not exists (
        select from results where object_name = file_path
    ) and file_size < 1153433600
    order by file_size desc
    '''

    # SELECTION_ID 4 / and 5 (to compare impact of week filter)
    fileset_query = '''
    select file_id, file_path,
        floor((extract(doy from time_start) - 1)/(365/48.))::integer + 1 as week
    from input_files
    where device_id = '3704-8490' and duration >= 3 and file_size < 1153433600
    order by time_start asc
    '''

    # SELECT_ID 6
    # a.k.a. the ultimate birdnet query
    # all files that:
    # - don't show up in results
    # - sampling rate == 48kHz
    # - duration >= 3s
    # - filesize < 1100MB

    # fileset_query = '''
    # select count(*)
    #     file_id, file_path,
    #     floor((extract(doy from time_start) - 1)/(365/48.))::integer + 1 as week
    # from input_files
    # where sample_rate = 48000 and duration >= 3 and not exists (
    #     select from results where object_name = file_path
    # ) and file_size < 1153433600
    # '''

    fileset_query = '''
    select file_id, file_path, floor((extract(doy from time_start) - 1)/(365/48.))::integer + 1 as week
    from input_files
    where sample_rate = 48000 and duration >= 3 and file_size >= 1153433600
    '''

    pg_server = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
    cursor = pg_server.cursor()

    cursor.execute(fileset_query)
    fileset = cursor.fetchall()
    files_count = len(fileset)

    cursor.close()
    pg_server.close()

    print(f'Found {files_count} files to analyze')

    # [(file_id, object_name)]
    return fileset

def loadCodes():

    with open(cfg.CODES_FILE, 'r') as cfile:
        codes = json.load(cfile)

    return codes

def loadLabels(labels_file):

    labels = []
    with open(labels_file, 'r') as lfile:
        for line in lfile.readlines():
            labels.append(line.replace('\n', ''))

    return labels

def loadSpeciesList(fpath):

    slist = []
    if not fpath == None:
        with open(fpath, 'r') as sfile:
            for line in sfile.readlines():
                species = line.replace('\r', '').replace('\n', '')
                slist.append(species)

    return slist

def predictSpeciesList():

    l_filter = model.explore(cfg.LATITUDE, cfg.LONGITUDE, cfg.WEEK)
    cfg.SPECIES_LIST_FILE = None
    cfg.SPECIES_LIST = []
    for s in l_filter:
        if s[0] >= cfg.LOCATION_FILTER_THRESHOLD:
            cfg.SPECIES_LIST.append(s[1])

def predictSpeciesLists():

    species_lists = []
    for w in range(1, 49):
        l_filter = model.explore(cfg.LATITUDE, cfg.LONGITUDE, w)
        species_lists.append([s[1] for s in l_filter if s[0] >= cfg.LOCATION_FILTER_THRESHOLD])
    return species_lists

def saveResultsToDb(f_id, object_name, r):
    insert_query = '''
    insert into
    results(file_id, object_name, time_start, time_end, confidence, species, selection_id)
    values %s
    '''

    pg_server = pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password)
    cursor = pg_server.cursor()

    data = []
    if PDEBUG: print('count of results:', len(r))
    for timestamp in sorted(r):
        for c in r[timestamp]:
            start, end = timestamp.split('-')
            if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                data.append((
                    f_id,
                    object_name,
                    float(start),
                    float(end),
                    float(c[1]),
                    label.split('_')[0],
                    SELECTION_ID))

    if PDEBUG: print('count of results after filtering:', len(data))
    execute_values(cursor, insert_query, data, template=None, page_size=100)
    pg_server.commit()
    cursor.close()
    pg_server.close()

def saveResultFile(r, path, afile_path):

    # Problems with writing results in chunks:
    # - headers are repeated (not in audacity)
    # - in type 'table', the selection_id repeats

    # Make folder if it doesn't exist
    if len(os.path.dirname(path)) > 0 and not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))

    # Selection table
    out_string = ''

    if cfg.RESULT_TYPE == 'table':

        # Raven selection header
        header = 'Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\tLow Freq (Hz)\tHigh Freq (Hz)\tSpecies Code\tCommon Name\tConfidence\n'
        selection_id = 0

        # Write header
        out_string += header

        # Extract valid predictions for every timestamp
        for timestamp in getSortedTimestamps(r):
            rstring = ''
            start, end = timestamp.split('-')
            for c in r[timestamp]:
                if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                    selection_id += 1
                    label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                    rstring += '{}\tSpectrogram 1\t1\t{}\t{}\t{}\t{}\t{}\t{}\t{:.4f}\n'.format(
                        selection_id,
                        start,
                        end,
                        150,
                        12000,
                        cfg.CODES[c[0]],
                        label.split('_')[1],
                        c[1])

            # Write result string to file
            if len(rstring) > 0:
                out_string += rstring

    elif cfg.RESULT_TYPE == 'audacity':

        # Audacity timeline labels
        for timestamp in getSortedTimestamps(r):
            rstring = ''
            for c in r[timestamp]:
                if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                    label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                    rstring += '{}\t{}\t{:.4f}\n'.format(
                        timestamp.replace('-', '\t'),
                        label.replace('_', ', '),
                        c[1])

            # Write result string to file
            if len(rstring) > 0:
                out_string += rstring

    elif cfg.RESULT_TYPE == 'r':

        # Output format for R
        header = 'filepath,start,end,scientific_name,common_name,confidence,lat,lon,week,overlap,sensitivity,min_conf,species_list,model'
        out_string += header

        for timestamp in getSortedTimestamps(r):
            rstring = ''
            start, end = timestamp.split('-')
            for c in r[timestamp]:
                if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                    label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                    rstring += '\n{},{},{},{},{},{:.4f},{:.4f},{:.4f},{},{},{},{},{},{}'.format(
                        afile_path,
                        start,
                        end,
                        label.split('_')[0],
                        label.split('_')[1],
                        c[1],
                        cfg.LATITUDE,
                        cfg.LONGITUDE,
                        cfg.WEEK,
                        cfg.SIG_OVERLAP,
                        (1.0 - cfg.SIGMOID_SENSITIVITY) + 1.0,
                        cfg.MIN_CONFIDENCE,
                        cfg.SPECIES_LIST_FILE,
                        os.path.basename(cfg.MODEL_PATH)
                    )
            # Write result string to file
            if len(rstring) > 0:
                out_string += rstring

    else:

        # CSV output file
        header = 'Start (s),End (s),Scientific name,Common name,Confidence\n'

        # Write header
        out_string += header

        for timestamp in getSortedTimestamps(r):
            rstring = ''
            for c in r[timestamp]:
                start, end = timestamp.split('-')
                if c[1] > cfg.MIN_CONFIDENCE and c[0] in cfg.CODES and (c[0] in cfg.SPECIES_LIST or len(cfg.SPECIES_LIST) == 0):
                    label = cfg.TRANSLATED_LABELS[cfg.LABELS.index(c[0])]
                    rstring += '{},{},{},{},{:.4f}\n'.format(
                        start,
                        end,
                        label.split('_')[0],
                        label.split('_')[1],
                        c[1])

            # Write result string to file
            if len(rstring) > 0:
                out_string += rstring

    # Save as file, appending to existing data
    with open(path, 'a') as rfile:
        rfile.write(out_string)


def getSortedTimestamps(results):
    return sorted(results, key=lambda t: float(t.split('-')[0]))


def getRawAudioFromFile(fpath):

    # Open file
    sig, rate = audio.openAudioFile(fpath, cfg.SAMPLE_RATE)

    # Split into raw audio chunks
    chunks = audio.splitSignal(sig, rate, cfg.SIG_LENGTH, cfg.SIG_OVERLAP, cfg.SIG_MINLEN)

    return chunks

def removeResultsFile(fpath):
    if os.path.isdir(cfg.OUTPUT_PATH):
        rpath = fpath
        rpath = rpath[1:] if rpath[0] in ['/', '\\'] else rpath
        if cfg.RESULT_TYPE == 'table':
            rtype = '.BirdNET.selection.table.txt'
        elif cfg.RESULT_TYPE == 'audacity':
            rtype = '.BirdNET.results.txt'
        else:
            rtype = '.BirdNET.results.csv'
        rfpath = os.path.join(cfg.OUTPUT_PATH, rpath.rsplit('.', 1)[0] + rtype)
        if os.path.exists(rfpath):
            if PDEBUG: print(f'removing existing result file: {rfpath}')
            os.remove(rfpath)
            try:
                os.removedirs(os.path.dirname(rfpath))
            except OSError:
                if PDEBUG: print(f'not removing {os.path.dirname(rfpath)} as it contains other files')

def predict(samples):

    # Prepare sample and pass through model
    data = np.array(samples, dtype='float32')
    prediction = model.predict(data)

    # Logits or sigmoid activations?
    if cfg.APPLY_SIGMOID:
        prediction = model.flat_sigmoid(np.array(prediction), sensitivity=-cfg.SIGMOID_SENSITIVITY)

    return prediction

def storeResults(f_id, fpath, results):

    try:
        # store results in database
        if PDEBUG: print('storing results for', fpath)
        saveResultsToDb(f_id, fpath, results)

        # store results to file

        # Make directory if it doesn't exist
        if len(os.path.dirname(cfg.OUTPUT_PATH)) > 0 and not os.path.exists(os.path.dirname(cfg.OUTPUT_PATH)):
            os.makedirs(os.path.dirname(cfg.OUTPUT_PATH))

        if os.path.isdir(cfg.OUTPUT_PATH):
            rpath = fpath
            rpath = rpath[1:] if rpath[0] in ['/', '\\'] else rpath
            if cfg.RESULT_TYPE == 'table':
                rtype = '.BirdNET.selection.table.txt'
            elif cfg.RESULT_TYPE == 'audacity':
                rtype = '.BirdNET.results.txt'
            else:
                rtype = '.BirdNET.results.csv'
            saveResultFile(results, os.path.join(cfg.OUTPUT_PATH, rpath.rsplit('.', 1)[0] + rtype), fpath)
        else:
            saveResultFile(results, cfg.OUTPUT_PATH, fpath)

    except:

        # Print traceback
        print(traceback.format_exc(), flush=True)

        # Write error log
        msg = f'Error: Cannot save result for {fpath}.\n{traceback.format_exc()}'
        print(msg, flush=True)
        writeErrorLog(msg)
        return False
    else:
        return True

def analyzeFile(item):

    # Get file path and restore cfg
    fpath = item[0]
    cfg.setConfig(item[1])
    f_id = item[2]

    # Start time
    start_time = datetime.datetime.now()

    # Status
    print(f'Analyzing {fpath}', flush=True)

    # Remove exsting result file
    removeResultsFile(fpath)

    temp_dir = tempfile.TemporaryDirectory()
    file = None

    # Read blocks of audio from file and process
    try:
        start, end = 0, cfg.SIG_LENGTH
        results = {}
        samples = []
        timestamps = []

        client = Minio(
            crd.minio.host,
            access_key=crd.minio.access_key,
            secret_key=crd.minio.secret_key,
        )

        # download file to temporary directory
        tmppath = os.path.join(temp_dir.name, os.path.basename(fpath))
        # TODO: if file < 15min: load it directly with client.get_object(crd.minio.bucket, fpath)
        # TODO: if samplerate != cfg.SAMPLE_RATE: resample
        client.fget_object(crd.minio.bucket, fpath, tmppath)
        file = sf.SoundFile(tmppath)

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
            p = predict(samples)

            # Add to results
            for i in range(len(samples)):

                # Get timestamp
                s_start, s_end = timestamps[i]

                # Get prediction
                pred = p[i]

                # Assign scores to labels
                p_labels = dict(zip(cfg.LABELS, pred))

                # Sort by score
                p_sorted =  sorted(p_labels.items(), key=operator.itemgetter(1), reverse=True)

                # Store results
                results[str(s_start) + '-' + str(s_end)] = p_sorted

            # store and clear results after a fixed number of blocks or last block
            # 1200: fits 60min of (non-overlapping) blocks in one go
            if block_count % 1200 == 0 or last_block:
                if PDEBUG: print(f'storing results at block {block_count}')
                storeResults(f_id, fpath, results)
                results = {}

            # Clear batch
            samples = []
            timestamps = []

            if PDEBUG: print(f'--end of analysis loop. block_count: {block_count}, last_block: {last_block}, {file.tell()}, {file.frames}')

            if file.tell() != file.frames and overlap_seek < 0:
                file.seek(overlap_seek, whence=sf.SEEK_CUR)

    except:
        # Print traceback
        print(traceback.format_exc(), flush=True)

        # Write error log
        msg = f'Error: Cannot analyze audio file {fpath}.\n{traceback.format_exc()}'
        print(msg, flush=True)
        writeErrorLog(msg)
        return False

    finally:
        file.close()
        temp_dir.cleanup()

    delta_time = (datetime.datetime.now() - start_time).total_seconds()
    print(f'Finished {fpath} in {delta_time:.2f} seconds', flush=True)

    return True

if __name__ == '__main__':

    # Freeze support for excecutable
    freeze_support()

    # Clear error log
    #clearErrorLog()

    # Parse arguments
    parser = argparse.ArgumentParser(description='Analyze audio files with BirdNET')
    parser.add_argument('--o', default='results/', help='Path to output folder.')
    parser.add_argument('--lat', type=float, required=True, help='Recording location latitude.')
    parser.add_argument('--lon', type=float, required=True, help='Recording location longitude.')
    # parser.add_argument('--week', type=int, default=-1, help='Week of the year when the recording was made. Values in [1, 48] (4 weeks per month). Set -1 for year-round species list.')
    # parser.add_argument('--slist', default='', help='Path to species list file or folder. If folder is provided, species list needs to be named \"species_list.txt\". If lat and lon are provided, this list will be ignored.')
    parser.add_argument('--sensitivity', type=float, default=1.0, help='Detection sensitivity; Higher values result in higher sensitivity. Values in [0.5, 1.5]. Defaults to 1.0.')
    parser.add_argument('--min_conf', type=float, default=0.1, help='Minimum confidence threshold. Values in [0.01, 0.99]. Defaults to 0.1.')
    parser.add_argument('--overlap', type=float, default=0.0, help='Overlap of prediction segments. Values in [0.0, 2.9]. Defaults to 0.0.')
    parser.add_argument('--rtype', default='table', help='Specifies output format. Values in [\'table\', \'audacity\', \'r\', \'csv\']. Defaults to \'table\' (Raven selection table).')
    parser.add_argument('--threads', type=int, default=4, help='Number of CPU threads.')
    parser.add_argument('--batchsize', type=int, default=1, help='Number of samples to process at the same time. Defaults to 1.')
    parser.add_argument('--locale', default='en', help='Locale for translated species common names. Values in [\'af\', \'de\', \'it\', ...] Defaults to \'en\'.')
    parser.add_argument('--sf_thresh', type=float, default=0.03, help='Minimum species occurrence frequency threshold for location filter. Values in [0.01, 0.99]. Defaults to 0.03.')

    args = parser.parse_args()

    # Set paths relative to script path (requested in #3)
    cfg.MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet',cfg.MODEL_PATH)
    cfg.LABELS_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.LABELS_FILE)
    cfg.TRANSLATED_LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.TRANSLATED_LABELS_PATH)
    cfg.MDATA_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.MDATA_MODEL_PATH)
    cfg.CODES_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'birdnet', cfg.CODES_FILE)

    cfg.ERROR_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), cfg.ERROR_LOG_FILE)

    # Load eBird codes, labels
    cfg.CODES = loadCodes()
    cfg.LABELS = loadLabels(cfg.LABELS_FILE)

    # Load translated labels
    lfile = os.path.join(cfg.TRANSLATED_LABELS_PATH, os.path.basename(cfg.LABELS_FILE).replace('.txt', '_{}.txt'.format(args.locale)))
    if not args.locale in ['en'] and os.path.isfile(lfile):
        cfg.TRANSLATED_LABELS = loadLabels(lfile)
    else:
        cfg.TRANSLATED_LABELS = cfg.LABELS

    ### Make sure to comment out appropriately if you are not using args. ###

    # Load species list from location filter or provided list
    cfg.LATITUDE, cfg.LONGITUDE = args.lat, args.lon
    cfg.LOCATION_FILTER_THRESHOLD = max(0.01, min(0.99, float(args.sf_thresh)))

    species_lists = predictSpeciesLists()

    # Set output path
    cfg.OUTPUT_PATH = args.o

    # Parse input files
    cfg.FILE_LIST = loadFileSet()

    # Set confidence threshold
    cfg.MIN_CONFIDENCE = max(0.01, min(0.99, float(args.min_conf)))

    # Set sensitivity
    cfg.SIGMOID_SENSITIVITY = max(0.5, min(1.0 - (float(args.sensitivity) - 1.0), 1.5))

    # Set overlap
    cfg.SIG_OVERLAP = max(0.0, min(2.9, float(args.overlap)))

    # Set result type
    cfg.RESULT_TYPE = args.rtype.lower()
    if not cfg.RESULT_TYPE in ['table', 'audacity', 'r', 'csv']:
        cfg.RESULT_TYPE = 'table'

    # Set number of threads
    cfg.CPU_THREADS = max(1, int(args.threads))
    cfg.TFLITE_THREADS = 1

    # Set batch size
    cfg.BATCH_SIZE = max(1, int(args.batchsize))

    # Add config items to each file list entry.
    # We have to do this for Windows which does not
    # support fork() and thus each process has to
    # have its own config. USE LINUX!
    flist = []
    for f_id, f, week in cfg.FILE_LIST:
        cfg.WEEK = week
        cfg.SPECIES_LIST = species_lists[week-1]
        flist.append((f, cfg.getConfig(), f_id))

    # Analyze files
    if cfg.CPU_THREADS < 2:
        for entry in flist:
            analyzeFile(entry)
    else:
        with Pool(cfg.CPU_THREADS) as p:
            p.map(analyzeFile, flist)

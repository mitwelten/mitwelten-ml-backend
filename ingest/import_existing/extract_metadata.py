import re
import mimetypes
import hashlib
import argparse
import audio_metadata

import psycopg2 as pg

import sys
sys.path.append('../../')
import credentials as crd

from datetime import datetime, timezone, timedelta, date
from os.path import basename, getsize
from tqdm.auto import tqdm
from psycopg2.extras import execute_values

BS = 65536

class FormatNotAudio(Exception):
    pass

class PathParseError(Exception):
    pass

rec_nok_str = {
    'microphone change': 'MICROPHONE_CHANGED',
    'change of switch position': 'SWITCH_CHANGED',
    'switch position change': 'SWITCH_CHANGED',
    'low voltage': 'SUPPLY_VOLTAGE_LOW',
    'magnetic switch': 'MAGNETIC_SWITCH',
    'file size limit': 'FILE_SIZE_LIMITED'
}

def extract_meta(path):
    info = {}
    file_size = getsize(path)
    file_type = mimetypes.guess_type(path)
    if file_type[0] == 'text/plain':
        raise FormatNotAudio('File is text', file_type[0])
    if file_type[0] == 'application/zip':
        raise FormatNotAudio('File is zip archive', file_type[0])
    if file_size == 0:
        raise FormatNotAudio('File is empty', 'empty')

    # create SHA256 hash
    file_hash = hashlib.sha256()
    with open(path, 'rb') as f:
        fb = f.read(BS)
        while len(fb) > 0:
            file_hash.update(fb)
            fb = f.read(BS)
    info['sha256'] = file_hash.hexdigest()

    # TODO: find sensible defaults if audiofile doesn't contain AudioMoth Data
    meta = audio_metadata.load(path)
    comment = meta.tags.comment[0]

    info['original_file_name'] = basename(meta.filepath)
    info['filesize'] = meta.filesize
    info['audio_format'] = meta.streaminfo.audio_format
    info['bit_depth'] = meta.streaminfo.bit_depth
    info['channels'] = meta.streaminfo.channels
    info['duration'] = meta.streaminfo.duration
    info['sample_rate'] = meta.streaminfo.sample_rate

    # Read the time and timezone from the header
    ts = re.search(r"(\d\d:\d\d:\d\d \d\d/\d\d/\d\d\d\d)", comment)[1]
    tz = re.search(r"\(UTC([-|+]\d+)?:?(\d\d)?\)", comment)
    hrs = 0 if tz[1] is None else int(tz[1])
    mins = 0 if tz[2] is None else -int(tz[2]) if hrs < 0 else int(tz[2])

    info['serial_number'] = re.search(r"by AudioMoth ([^ ]+)", comment)[1]

    extmic = re.search(r'using external microphone', comment)
    if extmic != None:
        info['source'] = 'external'
    else:
        info['source'] = 'internal'

    info['gain'] = re.search(r"at ([a-z-]+) gain", comment)[1]

    # - Band-pass filter with frequencies of 1.0kHz and 192.0kHz applied.
    # LOW_PASS_FILTER x, BAND_PASS_FILTER x y, HIGH_PASS_FILTER x
    bpf = re.search(r"Band-pass filter with frequencies of (\d+\.\d+)kHz and (\d+\.\d+)kHz applied\.", comment)
    lpf = re.search(r"Low-pass filter with frequency of (\d+\.\d+)kHz applied\.", comment)
    hpf = re.search(r"High-pass filter with frequency of (\d+\.\d+)kHz applied\.", comment)

    if bpf != None:
        info['filter'] = f'BAND_PASS_FILTER {bpf[1]} {bpf[2]}'
    elif lpf != None:
        info['filter'] = f'LOW_PASS_FILTER {lpf[1]}'
    elif hpf != None:
        info['filter'] = f'HIGH_PASS_FILTER {hpf[1]}'
    else:
        info['filter'] = 'NO_FILTER'

    timestamp = datetime.strptime(ts, "%H:%M:%S %d/%m/%Y")
    info['time_start'] = timestamp.replace(tzinfo=timezone(timedelta(hours=hrs, minutes=mins)))

    amp_res = re.search(r'Amplitude threshold was ([^ ]+) with ([^ ]+)s minimum trigger duration\.', comment)
    if amp_res != None:
        info['amp_thresh'], info['amp_trig'] = amp_res.groups()
    else:
        info['amp_thresh'], info['amp_trig'] = None, None # for postgres

    # Read the battery voltage and temperature from the header
    info['battery'] = re.search(r"(\d\.\d)V", comment)[1]
    info['temperature'] = re.search(r"(-?\d+\.\d)C", comment)[1]

    # read the remaining comment:
    #
    # !RECORDING_OKAY and ever only one more condition
    #
    # the AM recordings contain comments from several firmware versions!
    # the syntax differs (see test.py for unit tests of the expression):
    # - [old]     Recording cancelled before completion due to
    # - [...]     Recording stopped due to
    # - [current] Recording stopped
    #
    # MICROPHONE_CHANGED
    # - microphone change.
    # - due to microphone change.
    #
    # SWITCH_CHANGED
    # - change of switch position.
    # - switch position change.
    # - due to switch position change.
    #
    # MAGNETIC_SWITCH
    # - by magnetic switch.
    #
    # SUPPLY_VOLTAGE_LOW
    # - low voltage.
    # - due to low voltage.
    #
    # FILE_SIZE_LIMITED
    # - file size limit.
    # - due to file size limit.
    #
    # - Recording stopped due to switch position change.
    # - Recording cancelled before completion due to low voltage.
    #
    rec_nok = re.search(r" Recording (?:cancelled before completion|stopped) (?:by|due to) (magnetic switch|microphone change|change of switch position|switch position change|low voltage|file size limit)\.", comment)
    if rec_nok != None:
        info['rec_end_status'] = rec_nok_str[rec_nok[1]]
    else:
        info['rec_end_status'] = 'RECORDING_OKAY'

    return info

def extract_pathinfo(path, pattern_id):
    # SET A
    # Sound/FS1/fixed_AudioMoth/KW31_32/1874-8542/20210815_204501.WAV
    # CONFIG.TXT, CONFIG 2.TXT , *.zip should be allowed maybe
    if pattern_id == 'A':
        result = re.search(r".+\.zip|CONFIG\.TXT|config\.txt|.+/(KW[0-9_]+)/(?:Bats/(?:MG 26:10:22 )?)?(\d{4}[-_]\d{4})/(?:07:09:21-08:09:21/)?([^/]+\.WAV)", path)

    # SET B
    # Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG
    # date: 24:10:21 (d:m:y)
    # No config files and zips there
    elif pattern_id == 'B':
        result = re.search(r"Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG (\d{4}[-_]\d{4}) (\d\d):(\d\d):(\d\d) ?/Audioaufnahmen ?/([^/]+\.WAV)", path)

    # SET C
    # Life Science/Bats/Gundeli/Gundeli_09.2021/20210912_170000.WAV
    elif pattern_id == 'C':
        result = re.search(r"Life Science/Bats/Gundeli/Gundeli_\d\d\.\d\d\d\d/([^/]+\.WAV)", path)

    # SET D
    # Life Science/Grasshoppers/0863-3255 Villa 50 cm/20210907_193100.WAV
    # contains CONFIG.TXT, and audacity projects (ignore)
    elif pattern_id == 'D':
        result = re.search(r"Life Science/Grasshoppers/(\d{4}[-_]\d{4}) (.+)/([^/]+\.WAV)", path)

    # SET E
    # Life Science/6444-8804/20210912_112029.WAV
    # No config files and zips there
    elif pattern_id == 'E':
        result = re.search(r"Life Science/(\d{4}[-_]\d{4})/(\d{8}_\d{6}\.WAV)", path)

    # SET F: mitwelten_hd_small_1
    # KW20_21/2061-6644_2/20210519_212900.WAV , has config.txt and other stuff
    elif pattern_id == 'F':
        result = re.search(r"(KW[^/]+)/(\d{4}[-_]\d{4})(?:[-_]2)?/([^/]+\.(?:WAV|TXT|txt))", path)

    # SET G: mitwelten_hd_small_1
    # AM2_KW12/20210519_212900.WAV , no config.txt
    elif pattern_id == 'G':
        result = re.search(r"(AM\d)_(KW\d\d)/([^/]+\.WAV)", path)

    # parse results
    if result == None:
        raise PathParseError(f'unable to parse: {path}')
    else:
        device_id = None
        kw = None
        comment = None

        # SET A
        if pattern_id == 'A':
            kw, device_id, base_filename = result.groups()

        # SET B
        elif pattern_id == 'B':
            device_id, date_d, date_m, date_y, base_filename = result.groups()
            kw = date(int(f'20{date_y}'), int(date_m), int(date_d)).isocalendar().week

        # SET C
        elif pattern_id == 'C':
            base_filename = result[1]
            date_y, date_m, date_d = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}\.WAV", base_filename).groups()
            kw = date(int(date_y), int(date_m), int(date_d)).isocalendar().week

        # SET D
        elif pattern_id == 'D':
            device_id, comment, base_filename = result.groups()
            date_y, date_m, date_d = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}\.WAV", base_filename).groups() # same as SET C
            kw = date(int(date_y), int(date_m), int(date_d)).isocalendar().week # same as SET C

        # SET E
        elif pattern_id == 'E':
            device_id, base_filename = result.groups()
            date_y, date_m, date_d = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}\.WAV", base_filename).groups() # same as SET C
            kw = date(int(date_y), int(date_m), int(date_d)).isocalendar().week # same as SET C

        # SET F: mitwelten_hd_small_1
        # KW20_21/2061-6644_2/20210519_212900.WAV , has config txt and other shice
        elif pattern_id == 'F':
            kw, device_id, base_filename = result.groups()

        # SET G: mitwelten_hd_small_1
        # AM2_KW12/20210519_212900.WAV , no config.txt
        elif pattern_id == 'G':
            device_id, kw, base_filename = result.groups()

        return (kw, device_id, base_filename, comment)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extract data from audio files created by AudioMoth')
    parser.add_argument('--disk', help='disk name selector for files in DB', required=True)
    parser.add_argument('--mountpoint', help='local disk mount point', metavar='MP', required=True)
    parser.add_argument('--pattern', choices=['A', 'B', 'C', 'D', 'E', 'F', 'G'], help='pattern id for matching paths (check documentation)', required=True)
    parser.add_argument('--opath', help='original path selector for files in DB')
    parser.add_argument('--update_raw', action='store_true', help='1. update the raw file recordings (containing only original file path and disk information)')
    parser.add_argument('--check_empty', action='store_true', help='2. for files with invalid format, check if they are empty')
    args = parser.parse_args()

    # configure the targets
    disk = args.disk
    mountpoint = args.mountpoint
    path_prefix = '/'

    # connect to db
    pg_server = pg.connect(host=crd.db.host,
        port=crd.db.port,
        database=crd.db.database,
        user=crd.db.user,
        password=crd.db.password
    )
    cursor = pg_server.cursor()

    # allow for selecting a subset of files by matching the original file path
    if args.opath:
        if ((args.pattern == 'D' and args.opath != 'Life Science/Bats/Gundeli/Gundeli') or
            (args.pattern == 'E' and args.opath != 'Life Science/Grasshoppers') or
            (args.pattern == 'F' and args.opath != 'Life Science/64')):
            raise Exception(f'pattern selection {args.pattern} doesn\'t match opath {args.opath}')
        fileset_query = '''SELECT file_id, original_file_path from files where state is null and disk = %s and original_file_path like %s'''
        cursor.execute(fileset_query, (disk, f'{args.opath}%'))
    elif args.check_empty:
        fileset_query = '''SELECT file_id, original_file_path from files where (state is null or state = 'invalid format') and disk = %s'''
        cursor.execute(fileset_query, (disk,))
    else:
        fileset_query = '''SELECT file_id, original_file_path from files where (state is null or state = 'invalid path') and disk = %s '''
        cursor.execute(fileset_query, (disk,))

    fileset = cursor.fetchall()
    files_count = len(fileset)
    print(f'running on {files_count} records.')

    # update the raw file recordings (containing only original file path and disk information)
    # - parse the original file path from db
    # - extract audio metadata from disk
    # - update record
    if args.update_raw:
        count = 0
        progress = tqdm(total=files_count)
        for file_id, filepath in fileset:
            disk_filepath = mountpoint + path_prefix + filepath
            # extract information from file path
            try:
                kw, device_id, base_filename, comment = extract_pathinfo(disk_filepath, args.pattern)
                progress.write(f'--- {kw} {device_id} {base_filename} --- {disk_filepath}')
            except PathParseError as err:
                progress.write(err.__str__())
                # mark the record for inspection
                query = '''UPDATE files SET action = 'inspect', state = 'invalid path', updated_at = now() WHERE file_id = %s'''
                #cursor.execute(query, (file_id,))
                count += 1
                if count % 100 == 0:
                    progress.write(f'count: {count}, committing 100 records')
                    #pg_server.commit()
                progress.update(1)
                continue

            # extract metadata from file and write it to record
            try:
                info = extract_meta(disk_filepath)
                info['kw'] = kw
                info['device_id'] = device_id
                info['comment'] = comment
                query = '''UPDATE files SET
                        action = 'rename',
                        state = 'updated',
                        sha256 = %s,
                        time_start = %s,
                        file_size = %s,
                        format = %s,
                        sample_rate = %s,
                        bit_depth = %s,
                        channels = %s,
                        week = %s,
                        device_id = %s,
                        serial_number = %s,
                        battery = %s,
                        temperature = %s,
                        duration = %s,
                        gain = %s,
                        filter = %s,
                        source = %s,
                        rec_end_status = %s,
                        comment = %s,
                        updated_at = now()
                    WHERE file_id = %s
                '''
                # cursor.execute(query,
                #     (
                #         info['sha256'],
                #         info['time_start'],
                #         info['filesize'],
                #         info['audio_format'],
                #         info['sample_rate'],
                #         info['bit_depth'],
                #         info['channels'],
                #         info['kw'],
                #         info['device_id'],
                #         info['serial_number'],
                #         info['battery'],
                #         info['temperature'],
                #         info['duration'],
                #         info['gain'],
                #         info['filter'],
                #         info['source'],
                #         info['rec_end_status'],
                #         info['comment'],
                #         file_id
                #     )
                # )
                progress.write(info.__str__())

            except audio_metadata.exceptions.UnsupportedFormat as err:
                query = '''UPDATE files SET action = 'inspect', state = 'invalid format', updated_at = now() WHERE file_id = %s'''
                #cursor.execute(query, (file_id,))
                progress.write(f'{disk_filepath}: {err}')

            except FormatNotAudio as err:
                if err.args[1] == 'text/plain' and re.search('config.txt', base_filename, re.IGNORECASE):
                    progress.write(f'adding config file: {filepath}')
                    query = '''UPDATE files SET
                        action = 'rename', state = 'updated', format = 'text', updated_at = now()
                        week = %s,
                        device_id = %s,
                    WHERE file_id = %s'''
                    #cursor.execute(query, (kw, device_id, file_id))
                else:
                    if err.args[1] == 'application/zip':
                        progress.write(f'invalid format: {err.args[1]}')
                        query = '''UPDATE files SET action = 'inspect', state = 'invalid format', format = 'zip', updated_at = now() WHERE file_id = %s'''
                    elif err.args[1] == 'empty':
                        progress.write(f'invalid format: empty file')
                        query = '''UPDATE files SET action = 'ignore', state = 'empty audio', file_size = 0, updated_at = now() WHERE file_id = %s'''
                    else:
                        progress.write(f'invalid format: {err.args[1]}')
                        query = '''UPDATE files SET action = 'inspect', state = 'invalid format', updated_at = now() WHERE file_id = %s'''
                    #cursor.execute(query, (file_id,))

            finally:
                count += 1
                if count % 100 == 0:
                    progress.write('\n=========== committing 100 records ===========\n')
                    #pg_server.commit()
                progress.update(1)
        progress.write(f'count: {count}, committing remaining records')
        #pg_server.commit()
        progress.close()

    if args.check_empty:
        progress = tqdm(total=files_count)
        update_ids = []
        for file_id, filepath in fileset:
            disk_filepath = mountpoint + path_prefix + filepath
            file_size = getsize(disk_filepath)
            if file_size == 0:
                update_ids.append((file_id,))
            progress.update(1)
        progress.close()
        print(f'updating {len(update_ids)} records of empty audio files to be skipped')
        execute_values(cursor, '''
            UPDATE files SET state = 'empty audio', action = 'ignore', file_size = 0, updated_at = now()
            FROM (VALUES %s) AS data (file_id)
            WHERE files.file_id = data.file_id''',
        update_ids)
        pg_server.commit()
    cursor.close()
    pg_server.close()

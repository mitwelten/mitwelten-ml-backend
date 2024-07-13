import sys
import csv
from datetime import datetime

import psycopg2 as pg
sys.path.append('../../..')
import credentials as crd

deployments = [
    { 'id': 541, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' }, # FS 3
    { 'id': 679, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' }, # FS 3
    { 'id': 616, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' }, # FS 3
    { 'id': 503, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' }, # FS 3
    { 'id': 6, 'period_start': '2021-05-11 00:00:00', 'period_end': '2021-06-27 00:00:00' },   # FS 1
    { 'id': 3, 'period_start': '2021-05-11 00:00:00', 'period_end': '2021-06-27 00:00:00' },   # FS 1
    { 'id': 4, 'period_start': '2021-05-11 00:00:00', 'period_end': '2021-06-27 00:00:00' },   # FS 1
    { 'id': 5, 'period_start': '2021-05-11 00:00:00', 'period_end': '2021-06-27 00:00:00' },   # FS 1
    { 'id': 7, 'period_start': '2021-05-11 00:00:00', 'period_end': '2021-06-27 00:00:00' },   # FS 1
    { 'id': 1243, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' },# FS 2
    { 'id': 1261, 'period_start': '2023-05-11 00:00:00', 'period_end': '2023-06-27 00:00:00' },# FS 2
]

def import_filter(file_path):
    with open(file_path, 'r') as file:
        reader = csv.reader(file, delimiter='\t')
        species_filter = [(row[0] == 'TRUE', row[1]) for row in reader]
        return species_filter

def query_inferences(selection):
    'selection: (deployment_id, period_start, period_end, List[tuple(bool, str)])'
    deployment_id, period_start, period_end, species_filter = selection
    with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
        with conn.cursor() as cur:
            valid_species = [s[1] for s in species_filter if s[0]]
            query = '''
            select r.species, f.time + interval '1 second' * r.time_start as ts, r.confidence, f.deployment_id
            from prod.birdnet_results r
            join prod.files_audio f on r.file_id = f.file_id
            join prod.birdnet_tasks t on r.task_id = t.task_id
            where t.config_id = 1
                and f.deployment_id = %s
                and f.time between %s and %s
                and r.confidence >= 0.4
                and r.species in %s
                -- group by species
                order by ts
            '''
            cur.execute(query, (deployment_id, datetime.strptime(period_start, '%Y-%m-%d %H:%M:%S'), datetime.strptime(period_end, '%Y-%m-%d %H:%M:%S'), tuple(valid_species)))
            results = cur.fetchall()
            # write to file
            with open(f'data/inferences_{deployment_id}_filtered.csv', 'w') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(['species', 'time', 'confidence', 'deployment_id'])
                writer.writerows(results)

if __name__ == '__main__':
    for d in deployments:
        query_inferences((d['id'], d['period_start'], d['period_end'], import_filter(f'data/filter_{d["id"]}.tsv')))
        break

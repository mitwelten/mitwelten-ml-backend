
import sys
import psycopg2 as pg
from datetime import datetime
import json
import argparse
import os
import re

sys.path.append('../../..')
import credentials as crd

def main(output_file):
    objects = {}
    with open('select-birddiv.sql', 'r') as f:
        sql = f.read()
    with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
        with conn.cursor() as cur:
            # cur.execute('''
            # SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
            # FROM prod.birdnet_results r
            # JOIN prod.files_audio f ON r.file_id = f.file_id
            # JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
            # WHERE t.config_id = 1 and r.confidence >= 0.4
            # --AND "time" between '2021-05-09 00:00:00' and '2021-06-25 00:00:00'
            # --AND "time" between '2021-05-09 00:00:00' and '2021-05-11 00:00:00'
            # --AND f.deployment_id in (3,4,5,6,7)
            #   AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00' -- Bird Diversity - Validation Tasks DS / RH
            #   AND f.deployment_id in (3,4,5,6,7)
            # ORDER BY f.time asc;
            # ''')
            cur.execute(sql)
            data = cur.fetchall()
        for row in data:
            if row[0] not in objects:
                p = re.compile(r'(?P<nodelabel>\d{4}-\d{4})_(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})Z\.wav')
                i = p.match(os.path.basename(row[0])).groupdict()
                objects[row[0]] = {
                    "data": {
                        "file_id": row[1],
                        "header": f"{i['nodelabel']} {i['date'].replace('-','.')} {i['time'].replace('-',':')} UTC",
                        "audio": f"s3://ixdm-mitwelten/{row[0]}",
                        "node_label": i['nodelabel']
                    },
                    "predictions": [
                        {
                            "model_version": 'BirdNET_GLOBAL_2K_V2.1_Model_FP32',
                            "result": []
                        }
                    ]
                }
            result = {
                "original_length": row[3],
                "value": {
                    "start": row[5],
                    "end": row[6],
                    "channel": 0,
                    "score": row[7],
                    "labels": [ row[4] ]
                },
                "from_name": "label",
                "to_name": "audio",
                "type": "labels"
            }
            objects[row[0]]['predictions'][0]['result'].append(result)

    # go through all objects and extract the labels from the predictions, insert them as a list into the data field
    for obj in objects.values():
        obj['data']['species'] = [{"value": v} for v in set([r['value']['labels'][0] for r in obj['predictions'][0]['result']])]

    json_data = []
    if len(objects) > 1000:
        output_file = os.path.splitext(output_file)[0]
        for i, prediction in enumerate(objects.values()):
            if i % 1000 == 0 and i > 0:
                step = i - 999
                with open(f'{output_file}_{step}.json', 'w') as file:
                    json.dump(json_data, file, indent=2)
                json_data = []
            json_data.append(prediction)

        if len(json_data):
            with open(f'{output_file}_last.json', 'w') as file:
                json.dump(json_data, file, indent=2)
    else:
        with open(list(output_file), 'w') as file:
            json.dump(json_data, file, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import records from a CSV file (export from DB) and output them as JSON tasks for LabelStudio.')
    parser.add_argument('output_file', type=str, help='Output JSON file')
    args = parser.parse_args()

    main(args.output_file)


import json
import argparse
import os
import re

def main(output_file):
    objects = {}
    # read sample from json file
    with open('bats_results_sample.json', 'r') as file:
        data = json.load(file)

    for row in data:
        if row['file_id'] not in objects:
            p = re.compile(r'(?P<nodelabel>\d{4}-\d{4})_(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})Z\.wav')
            i = p.match(os.path.basename(row['object_name'])).groupdict()
            objects[row['file_id']] = {
                "data": {
                    "file_id": row['file_id'],
                    "header": f"{i['nodelabel']} {i['date'].replace('-','.')} {i['time'].replace('-',':')} UTC",
                    "audio": f"s3://ixdm-mitwelten/{row['object_name']}"
                },
                "predictions": [
                    {
                        "model_version": 'batnet v2.0',
                        "result": []
                    }
                ]
            }
        result = {
            "original_length": 55,
            "value": {
                "start": row['start_time'],
                "end": row['end_time'],
                "low_freq": row['low_freq'],
                "high_freq": row['high_freq'],
                "score": row['class_prob'],
                "labels": [ row['class'] ]
            },
            "from_name": "label",
            "to_name": "audio",
            "type": "labels"
        }
        objects[row['file_id']]['predictions'][0]['result'].append(result)

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
        with open(output_file, 'w') as file:
            json.dump(list(json_data), file, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import records from a CSV file (export from DB) and output them as JSON tasks for LabelStudio.')
    parser.add_argument('output_file', type=str, help='Output JSON file')
    args = parser.parse_args()

    main(args.output_file)

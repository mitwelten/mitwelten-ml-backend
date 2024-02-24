import json
import argparse
import os
import re

def main(output_file):
    objects = {}
    # read sample from json file
    with open('bats_sample.json', 'r') as file:
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
                }
            }

    json_data = []
    if len(objects) > 1000:
        output_file = os.path.splitext(output_file)[0]
        for i, annotation in enumerate(objects.values()):
            if i % 1000 == 0 and i > 0:
                step = i - 999
                with open(f'{output_file}_{step}.json', 'w') as file:
                    json.dump(json_data, file, indent=2)
                json_data = []
            json_data.append(annotation)

        if len(json_data):
            with open(f'{output_file}_last.json', 'w') as file:
                json.dump(json_data, file, indent=2)
    else:
        with open(output_file, 'w') as file:
            json.dump(list(objects.values()), file, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import records from a CSV file (export from DB) and output them as JSON tasks for LabelStudio.')
    parser.add_argument('output_file', type=str, help='Output JSON file')
    args = parser.parse_args()

    main(args.output_file)

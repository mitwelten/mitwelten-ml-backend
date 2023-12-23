import csv
import json
import argparse
import os
import re

# import predictions from a csv file and output them as json task list for labelstudio

def main(csv_file, output_file):
    # Step 1: Read the CSV file and create a list of predictions
    objects = {}
    with open(csv_file, 'r') as file:
        csv_reader = csv.DictReader(file, delimiter=';')
        for row in csv_reader:
            if row['object_name'] not in objects:
                p = re.compile(r'(?P<nodelabel>\d{4}-\d{4})_(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})Z\.jpg')
                i = p.match(os.path.basename(row['object_name'])).groupdict()
                objects[row['object_name']] = {
                    "data": {
                        "file_id": row['file_id'],
                        "header": f"{i['nodelabel']} {i['date'].replace('-','.')} {i['time'].replace('-',':')} UTC",
                        "image": f"s3://ixdm-mitwelten/{row['object_name']}"
                    },
                    "predictions": [
                        {
                            "model_version": row['config_id'],
                            "result": []
                        }
                    ]
                }

            result = {
                "original_width": int(row['o_width']),
                "original_height": int(row['o_height']),
                "image_rotation": 0,
                "value": {
                    "x": float(row['x']),
                    "y": float(row['y']),
                    "width": float(row['width']),
                    "height": float(row['height']),
                    "score": float(row['score']),
                    "rotation": 0,
                    "rectanglelabels": [
                        row['label']
                    ]
                },
                "id": row['inferrence_id'],
                "from_name": "flower" if row['label'] in ['daisy', 'flockenblume', 'wildemoere'] else "pollinator",
                "to_name": "image",
                "type": "rectanglelabels",
                "readonly": False
            }
            objects[row['object_name']]['predictions'][0]['result'].append(result)

    # Step 2: Split the JSON data into chunks of 1000 objects
    json_data = []
    pval = objects.values()
    if len(objects) > 1000:
        output_file = os.path.splitext(output_file)[0]
        for i, prediction in enumerate(objects.values()):
            if i % 1000 == 0 and i > 0:
                print(f'processing {i} of {len(pval)}')
                step = i - 999
                with open(f'{output_file}_{step}.json', 'w') as file:
                    json.dump(json_data, file, indent=2)
                json_data = []
            json_data.append(prediction)

        if len(json_data):
            with open(f'{output_file}_last.json', 'w') as file:
                json.dump(json_data, file, indent=2)
    else:
        output_file = f'{output_file}'
        for i, prediction in enumerate(objects.values()):
            json_data.append(prediction)
        with open(output_file, 'w') as file:
            json.dump(json_data, file, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import predictions from a CSV file (export from DB) and output them as JSON for LabelStudio.')
    parser.add_argument('csv_file', type=str, help='Input CSV file')
    parser.add_argument('output_file', type=str, help='Output JSON file')
    args = parser.parse_args()

    main(args.csv_file, args.output_file)

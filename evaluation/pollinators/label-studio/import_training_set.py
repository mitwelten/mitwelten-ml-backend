import csv
import json
import argparse
import os
import re
import sys
import psycopg2 as pg

sys.path.append('../../..')
import credentials as crd

labels = ('daisy', 'wildemoere', 'flockenblume')

# import predictions from a csv file and output them as json for labelstudio

def main(labelset, output_file):
    objects = {}
    with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
        for csv_file in labelset:
            # Step 1: Read the CSV file and create a list of predictions
            task = {}
            with open(csv_file, 'r') as file:
                # format: class(int), x(float), y(float), width(float), height(float)
                # i.e: 0 0.7817073170731708 0.8944805194805194 0.0475609756097561 0.06168831168831169
                csv_reader = csv.DictReader(file, delimiter=' ', fieldnames=['class', 'x', 'y', 'width', 'height'])
                object_key = os.path.splitext(os.path.basename(csv_file))[0]
                p = re.compile(r'(?P<nodelabel>\d{4}-\d{4})_(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})Z')
                i = p.match(object_key).groupdict()
                object_name = f"{i['nodelabel']}/{i['date']}/{i['time'][0:2]}/{object_key}.jpg"
                # check if object exists in db
                with conn.cursor() as cur:
                    cur.execute('select file_id, resolution from prod.files_image where object_name = %s;', (object_name,))
                    row = cur.fetchone()
                    if row is None:
                        print(f'object {object_name} not found in db')
                        continue
                    else:
                        # extract file_id, width and height from db
                        i['file_id'] = row[0]
                        i['width'] = row[1][0]
                        i['height'] = row[1][1]
                task = {
                    "data": {
                        "file_id": i['file_id'],
                        "header": f"{i['nodelabel']} {i['date'].replace('-','.')} {i['time'].replace('-',':')} UTC",
                        "image": f"s3://ixdm-mitwelten/{object_name}"
                    },
                    "predictions": [
                        {
                            "model_version": 'training_set',
                            "result": []
                        }
                    ]
                }
                for row in csv_reader:
                    result = {
                        "original_width": int(i['width']),
                        "original_height": int(i['height']),
                        "image_rotation": 0,
                        "value": {
                            "x": (float(row['x']) - (float(row['width']) / 2)) * 100,
                            "y": (float(row['y']) - (float(row['height']) / 2)) * 100,
                            "width": float(row['width']) * 100,
                            "height": float(row['height']) * 100,
                            "rotation": 0,
                            "rectanglelabels": [
                                labels[int(row['class'])]
                            ]
                        },
                        # "id": row['inferrence_id'],
                        "from_name": "flower",
                        "to_name": "image",
                        "type": "rectanglelabels",
                        "readonly": True
                    }
                    task['predictions'][0]['result'].append(result)
                objects[object_name] = task
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
    parser = argparse.ArgumentParser(description='Import training/test labels from a textfiles and output them as JSON for LabelStudio.')
    parser.add_argument('input_path', type=str, help='Input Path')
    parser.add_argument('output_path', type=str, help='Output Path')
    args = parser.parse_args()

    test_labels = []
    training_labels = []
    for root, dirs, files in os.walk(args.input_path):
        label_type = os.path.basename(root)
        for file in files:
            if file.endswith('.txt'):
                if label_type == 'test':
                    test_labels.append(os.path.join(root, file))
                else:
                    training_labels.append(os.path.join(root, file))

    main(test_labels, args.output_path + '/test.json')
    main(training_labels, args.output_path + '/training.json')

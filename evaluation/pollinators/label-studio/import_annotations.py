import csv
import json
import argparse
import os
import re

# import image records from a csv file and output them as json task list for labelstudio

def main(csv_file, output_file):
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
                    }
                }
    json_data = []
    output_file = f'{output_file}'
    for i, prediction in enumerate(objects.values()):
        json_data.append(prediction)
    with open(output_file, 'w') as file:
        json.dump(json_data, file, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import records from a CSV file (export from DB) and output them as JSON tasks for LabelStudio.')
    parser.add_argument('csv_file', type=str, help='Input CSV file')
    parser.add_argument('output_file', type=str, help='Output JSON file')
    args = parser.parse_args()

    main(args.csv_file, args.output_file)

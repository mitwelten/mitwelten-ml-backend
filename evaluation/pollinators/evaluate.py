import argparse
import json
import os
import psycopg2 as pg
from minio import Minio
import sys

import tqdm

sys.path.append('../..')
import credentials as crd

'''
This script is used to compare the ground truth data (labels created manually in
[label studio](label.mitwelten.org)) with the predictions in the database.
'''

def read_tasks_from_minio():
    # read all tasks from minio storage
    bucket = 'ixdm-mitwelten-labels'
    s3 = Minio(
        crd.minio.host,
        access_key=crd.minio.access_key,
        secret_key=crd.minio.secret_key,
    )
    object_list = s3.list_objects(bucket, recursive=False)
    tasks = []
    tqdm.write('reading tasks from minio storage...')
    for obj in tqdm.tqdm(object_list):
        data = json.loads(s3.get_object(bucket, obj.object_name).read())
        if 'file_id' in data['task']['data']:
            tasks.append(data)

    # write tasks to json file
    os.path.makedirs('ground_truth', exist_ok=True)
    with open('ground_truth/tasks.json', 'w') as f:
        json.dump(tasks, f)

def intersect(x1, y1, w1, h1, x2, y2, w2, h2):
    x_left = max(x1,x2)
    y_top = max(y1,y2)
    x_right = min(x1+w1,x2+w2)
    y_bottom = min(y1+h1,y2+h2)
    if x_right < x_left or y_bottom < y_top:
        return 0
    return (x_right - x_left) * (y_bottom - y_top)

def iou(x1, y1, w1, h1, x2, y2, w2, h2):
    intersection = intersect(x1, y1, w1, h1, x2, y2, w2, h2)
    union = w1 * h1 + w2 * h2 - intersection
    return intersection / union

def match_p(gt, p_rects, threshold=0.5):
    '''
    gt: ground truth rectangle
        {'height': 5.387647831800252,
        'rectanglelabels': ['daisy'],
        'rotation': 0,
        'width': 3.9466970119800706,
        'x': 55.352522946178254,
        'y': 65.17739816031539}
    p_rects: prediction rectangles
        ('daisy',
        0.8567697,
        Decimal('41.8814432989690722'),
        Decimal('44.7654462242562929'),
        Decimal('2.5987972508591065'),
        Decimal('3.9473684210526316'))
    '''
    # 0 confidence, 1 class, 2 x, 3 y, 4 width, 5 height
    for i, p in enumerate(p_rects):
        # match class
        if gt['rectanglelabels'][0] != p[0]:
            continue
        # match rectangle
        if iou(
            gt['x'], gt['y'], gt['width'], gt['height'],
            float(p[2]), float(p[3]), float(p[4]), float(p[5])) > threshold:
            return i
    return None

def match_gt(p, gt_rects, threshold=0.5):
    # 0 confidence, 1 class, 2 x, 3 y, 4 width, 5 height
    for i, gt in enumerate(gt_rects):
        # match class
        if p[0] != gt['rectanglelabels'][0]:
            continue
        # match rectangle
        metric = iou(
            gt['x'], gt['y'], gt['width'], gt['height'],
            float(p[2]), float(p[3]), float(p[4]), float(p[5]))
        if metric > threshold:
            return i
    return None

def match_all(gt_rects, p_rects, threshold=0.5):
    false_positives = [] # p_rects that are not matched
    false_negatives = [] # gt_rects that are not matched
    true_positives  = [] # gt_rects that are matched
    for gt in gt_rects:
        # match_index is the index of the matched rectangle in p_rects
        match_index = match_p(gt, p_rects, threshold)
        if match_index is not None:
            true_positives.append({ 'gt': gt, 'p': p_rects[match_index] })
        else:
            false_negatives.append(gt)
    # false positives are all p_rects that are not matched
    for p in p_rects:
        match_index = match_gt(p, gt_rects, threshold)
        if match_index is None:
            false_positives.append(p)
    return (false_positives, false_negatives, true_positives)


def main(user_id, threshold_flowers, threshold_pollinators):
    # read tasks from minio storage
    if not os.path.exists('ground_truth/tasks.json'):
        read_tasks_from_minio()

    # read tasks from json file
    tasks_grouped = {}
    with open('ground_truth/tasks.json', 'r') as f:
        tasks = json.load(f)
        # there are multiple objects with the same task id those are labels by
        # different users. group the objects by task id.
        for t in tasks:
            task_id = t['task']['id']
            task_user = t['completed_by']['id']
            if task_id not in tasks_grouped:
                tasks_grouped[task_id] = {}
            result = [r for r in t['result'] if r['from_name'] in ['pollinator', 'flower']]
            tasks_grouped[task_id][task_user] = { 'task': t['task'], 'result': result, 'project': t['project'] }

    # print CSV header
    print('task_id, file_id, fl_fp, fl_fn, fl_tp, fl_f1, po_fp, po_fn, po_tp, po_f1')

    with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
        for task in tasks_grouped.values():
            data = None
            # each task has results from multiple users, select one
            if user_id in task:
                data = task[user_id]
            else:
                continue

            file_id = int(data['task']['data']['file_id'])

            with conn.cursor() as cur:
                # get result id from file id
                cur.execute('select result_id from prod.image_results where file_id = %s;', (file_id,))
                result_id, = cur.fetchone()

                if len(data['result']) > 0:
                    w = int(data['result'][0]['original_width'])
                    h = int(data['result'][0]['original_height'])
                    # get flower predictions for result id
                    cur.execute('''
                    select
                        f.class as label,
                        f.confidence as score,
                        f.x0 * 100. / %s as x,
                        f.y0 * 100. / %s as y,
                        (f.x1 - f.x0) * 100. / %s as width,
                        (f.y1 - f.y0) * 100. / %s as height
                    from prod.flowers f
                    where f.result_id = %s
                    and class not in ('wildemoere');
                    ''', (w,h,w,h, result_id))
                    p_flowers = cur.fetchall()

                    # get pollinator predictions for result id
                    cur.execute('''
                    select
                        p.class as label,
                        p.confidence as score,
                        p.x0 * 100. / %s as x,
                        p.y0 * 100. / %s as y,
                        (p.x1 - p.x0) * 100. / %s as width,
                        (p.y1 - p.y0) * 100. / %s as height
                    from prod.pollinators p
                    where p.result_id = %s;
                    ''', (w,h,w,h, result_id))
                    p_pollinators = cur.fetchall()
                else:
                    cur.execute('''
                    select
                        f.class as label,
                        f.confidence as score
                    from prod.flowers f
                    where f.result_id = %s;
                    ''', (result_id,))
                    p_flowers = cur.fetchall()
                    cur.execute('''
                    select
                        f.class as label,
                        f.confidence as score
                    from prod.pollinators f
                    where f.result_id = %s;
                    ''', (result_id,))
                    p_pollinators = cur.fetchall()

            # get flower/pollinator rectangles from ground truth data
            gt_flowers = [r['value'] for r in data['result'] if r['type'] == 'rectanglelabels' and r['from_name'] == 'flower']
            gt_pollinators = [r['value'] for r in data['result'] if r['type'] == 'rectanglelabels' and r['from_name'] == 'pollinator']

            # match ground truth rectangles with predictions
            fl_fp, fl_fn, fl_tp = match_all(gt_flowers, p_flowers, threshold_flowers)
            po_fp, po_fn, po_tp = match_all(gt_pollinators, p_pollinators, threshold_pollinators)

            # flower scores
            fl_precision = len(fl_tp) / (len(fl_tp) + len(fl_fp)) if len(fl_tp) + len(fl_fp) != 0 else 1
            fl_recall = len(fl_tp) / (len(fl_tp) + len(fl_fn)) if len(fl_tp) + len(fl_fn) != 0 else 1
            fl_f1 = 2 * (fl_precision * fl_recall) / (fl_precision + fl_recall) if fl_precision + fl_recall != 0 else 0

            # pollinator scores
            po_precision = len(po_tp) / (len(po_tp) + len(po_fp)) if len(po_tp) + len(po_fp) != 0 else 1
            po_recall = len(po_tp) / (len(po_tp) + len(po_fn)) if len(po_tp) + len(po_fn) != 0 else 1
            po_f1 = 2 * (po_precision * po_recall) / (po_precision + po_recall) if po_precision + po_recall != 0 else 0

            # print results
            print(f"{data['task']['id']}, {data['task']['data']['file_id']}, {len(fl_fp)}, {len(fl_fn)}, {len(fl_tp)}, {fl_f1:.3f}, {len(po_fp)}, {len(po_fn)}, {len(po_tp)}, {po_f1:.3f}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluate predictions with ground truth data.')
    parser.add_argument('user_id', type=int, help='User ID', default=5)
    parser.add_argument('threshold_flowers', type=float, help='IoU threshold for matching flowers (0...1)', default=0.4)
    parser.add_argument('threshold_pollinators', type=float, help='IoU threshold for matching pollinators (0...1)', default=0.3)
    args = parser.parse_args()

    main(args.user_id, args.threshold_flowers, args.threshold_pollinators)

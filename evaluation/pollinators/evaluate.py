import argparse
import json
import os
import psycopg2 as pg
from minio import Minio
import sys

from tqdm import tqdm

sys.path.append('../..')
import credentials as crd

'''
This script is used to compare the ground truth data (labels created manually in
[label studio](label.mitwelten.org)) with the predictions in the database.
'''

def read_tasks_from_minio(cache_file):
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
    for obj in tqdm(object_list):
        data = json.loads(s3.get_object(bucket, obj.object_name).read())
        # 'file_id' is our custom field, and is the id used in files_images table in the database
        if 'file_id' in data['task']['data']:
            tasks.append(data)

    # write tasks to json file
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, 'w') as f:
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
    match prediction

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
    'match ground truth'
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

def evaluate_with_groundtruth(tasks, threshold_flowers, threshold_pollinators):
    '''
    # Evaluate predictions with manual labels

    current situation: a predefined set of images was exported from the
    database as label studio tasks. in those tasks, multiple users labelled
    flowers and pollinators in the images. the labels are rectangles with
    classes and confidence values, and optional notes. the labels are used as
    ground truth data to evaluate the predictions inferred by our model from
    the same set of images.

    the manual labels are associated to the predictions by finding the
    prediction with the highest IoU (intersection over union) with the ground
    truth label. if the IoU is above a certain threshold, then the prediction is
    considered a true positive. if the IoU is below the threshold, then the
    prediction is considered a false positive. if there is no prediction for a
    ground truth label, then the label is considered a false negative.

    the precision, recall and f1 score are calculated for the flowers and
    pollinators separately.
    '''

    stats = {
        'fl_fp': 0, 'fl_fn': 0, 'fl_tp': 0,
        'po_fp': 0, 'po_fn': 0, 'po_tp': 0
    }

    with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
        tqdm.write('comparing labels to predictions in database...')
        for data in tqdm(tasks):

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

            # update stats
            stats['fl_fp'] += len(fl_fp)
            stats['fl_fn'] += len(fl_fn)
            stats['fl_tp'] += len(fl_tp)
            stats['po_fp'] += len(po_fp)
            stats['po_fn'] += len(po_fn)
            stats['po_tp'] += len(po_tp)

    # print stats
    # flower scores
    fl_precision = stats['fl_tp'] / (stats['fl_tp'] + stats['fl_fp']) if stats['fl_tp'] + stats['fl_fp'] != 0 else 1
    fl_recall = stats['fl_tp'] / (stats['fl_tp'] + stats['fl_fn']) if stats['fl_tp'] + stats['fl_fn'] != 0 else 1
    fl_f1 = 2 * (fl_precision * fl_recall) / (fl_precision + fl_recall) if fl_precision + fl_recall != 0 else 0
    print('---')
    print('flower scores')
    print('precision:', fl_precision)
    print('recall:', fl_recall)
    print('f1 score:', fl_f1)

    # pollinator scores
    po_precision = stats['po_tp'] / (stats['po_tp'] + stats['po_fp']) if stats['po_tp'] + stats['po_fp'] != 0 else 1
    po_recall = stats['po_tp'] / (stats['po_tp'] + stats['po_fn']) if stats['po_tp'] + stats['po_fn'] != 0 else 1
    po_f1 = 2 * (po_precision * po_recall) / (po_precision + po_recall) if po_precision + po_recall != 0 else 0
    print('---')
    print('pollinator scores')
    print('precision:', po_precision)
    print('recall:', po_recall)
    print('f1 score:', po_f1)

def evaluate_with_confidence(tasks):
    '''
    # Evaluate predictions with manual confidences

    current situation: predictions where labelled as true or false positives,
    each task has multiple results that are linked by a common id. the results
    have different types: rectanglelabels, choices and textarea.

    rectanglelabels:    contains the label and the rectangle coordinates
                        (['value']['rectanglelabels'] = ['wildbiene'])
    choices:            contains the manually assigned confidence value
                        (['value']['choices'] = ['false positive'], the choices
                        being 'false positive', 'high confidence', 'medium
                        confidence' or 'low confidence')
    textarea:           contains notes (['value']['text'] = ['this is a note'])

    if the confidence is 'false positive' then the rectangle is a false
    positive, if the confidence is 'high confidence', 'medium confidence' or
    'low confidence' then the rectangle is a true positive.

    of all results, calculate the precision. recall and f1 score cannot be
    calculated without knowing about false negatives (and ideally true
    negatives). the results are also split by pollinator class.
    '''

    conditions = []
    # get tasks by specified user only
    for task in tasks:
        results_by_id = {}
        for result in task['result']:
            for confidence in task['confidence']:
                if confidence['id'] == result['id']:
                    result['test_result'] = confidence['value']['choices'][0]
                    # condition tuple: (class, confidence)
                    conditions.append((result['value']['rectanglelabels'][0], confidence['value']['choices'][0]))
            results_by_id[result['id']] = result
    true_positives = [r for r in conditions if r[1] in ['high confidence', 'medium confidence', 'low confidence']]
    false_positives = [r for r in conditions if r[1] == 'false positive']

    # there can be multiple results per task, so the length of the conditions
    # list is not equal to the number of tasks
    print(f'of {len(conditions)} predictions: {len(true_positives)} TP, {len(false_positives)} FP')
    print(f'overall precision or (positive predictive value, PPV): {len(true_positives) / (len(true_positives) + len(false_positives)):.3f}')

    tp_classes = {}
    fp_classes = {}
    for c in conditions:
        if c[1] in ['high confidence', 'medium confidence', 'low confidence']:
            if c[0] not in tp_classes:
                tp_classes[c[0]] = 0
            tp_classes[c[0]] += 1
        else:
            if c[0] not in fp_classes:
                fp_classes[c[0]] = 0
            fp_classes[c[0]] += 1

    print('---')
    print('precision (PPV) by class')
    print('tp', 'fp', 'ppv', 'class', sep='\t')
    for c in ['fliege', 'honigbiene', 'hummel', 'schwebfliege', 'wildbiene']:
        precision = tp_classes.get(c, 0) / (tp_classes.get(c, 0) + fp_classes.get(c, 0))
        print(tp_classes.get(c, 0), fp_classes.get(c, 0), f'{precision:.3f}', c, sep='\t')

def main(mode, project_id, user_id, threshold_flowers, threshold_pollinators):
    # read tasks from minio storage
    cache_file = f'ground_truth/labelstudio_tasks.json'
    if not os.path.exists(cache_file):
        read_tasks_from_minio(cache_file)

    if mode == 'confidences':
        origins = ['prediction-changed', 'prediction']
    if mode == 'labels':
        origins = ['manual']

    # read tasks from json file
    tasks_grouped = {}
    with open(cache_file, 'r') as f:
        tasks = json.load(f)
        # there are multiple objects with the same task id those are labels by
        # different users. group the objects by task id.
        for t in tasks:
            if t['task']['project'] != project_id:
                continue
            if t['task']['is_labeled'] == False: # tasks without targets that are completed have this set to True.
                continue
            if t['was_cancelled'] == True:
                continue

            task_user = t['completed_by']['id']
            task_id = t['task']['id']
            if task_user not in tasks_grouped:
                tasks_grouped[task_user] = {}
            if task_id not in tasks_grouped[task_user]:
                tasks_grouped[task_user][task_id] = {}
            result = [r for r in t['result'] if r['origin'] in origins and r['from_name'] in ['pollinator', 'flower']]
            confidence = [r for r in t['result'] if r['origin'] in origins and r['from_name'] == 'confidence']
            tasks_grouped[task_user][task_id] = { 'task': t['task'], 'result': result, 'confidence': confidence, 'project': t['project'] }

    print('running mode:', mode)
    print('project id:', project_id)
    print('user id:', user_id)
    print(f'found {len(tasks_grouped[user_id])} tasks')
    if mode == 'labels':
        print(f'thresholds: flowers = {threshold_flowers}, pollinators = {threshold_pollinators}')

    # count tasks that have confidence labels
    annotated_rectangles = 0
    annotated_confidences = 0
    for task in tasks_grouped[user_id].values():
        # for specified user and project only
        if task['project'] == project_id:
            if len(task['result']) > 0:
                annotated_rectangles += 1
            if len(task['confidence']) > 0:
                annotated_confidences += 1
            else:
                # this is ok, in labels mode there can be tasks that don't contain targets
                if mode == 'confidences':
                    print(f'no confidence labels for task {task["task"]["id"]}')

    print('---')
    print(f'found {annotated_rectangles} annotations with predictions')
    print(f'found {annotated_confidences} annotations with confidence labels')

    # if tasks_with_rectangles and tasks_with_confidence are not equal, then the
    # set is incomplete and the evaluation cannot be performed
    if annotated_rectangles != annotated_confidences:
        print('incomplete set, cannot perform evaluation')
        sys.exit(1)

    # evaluate predictions with manual confidences
    if mode == 'confidences':
        # fold annotations of two users into one
        # other user_ids present in the dataset
        other_users = list(filter(lambda x: x != user_id, tasks_grouped.keys()))
        other_tasks = []
        if len(other_users) > 0:
            # get tasks unique to the first user
            unique_task_ids = set(tasks_grouped[other_users[0]].keys()) - set(tasks_grouped[user_id].keys())
            print(f'found {len(unique_task_ids)} tasks unique to another user, adding them to the evaluation...')
            other_tasks = [tasks_grouped[other_users[0]][task_id] for task_id in unique_task_ids]
        evaluate_with_confidence(list(tasks_grouped[user_id].values()) + other_tasks)

    # evaluate predictions with manual labels
    if mode == 'labels':
        evaluate_with_groundtruth(tasks_grouped[user_id].values(), threshold_flowers, threshold_pollinators)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluate predictions with ground truth data.')
    parser.add_argument('mode', type=str, help='Mode: Compare predictions with manual labels or manual confidences', choices=['labels', 'confidences'])
    parser.add_argument('-p', '--project_id', type=int, help='Label Studio Project ID', default=5)
    parser.add_argument('-u', '--user_id', type=int, help='Label Studio User ID', default=5)
    parser.add_argument('-tf', '--threshold_flowers', type=float, help='IoU threshold for matching flowers (0...1)', default=0.4)
    parser.add_argument('-tp', '--threshold_pollinators', type=float, help='IoU threshold for matching pollinators (0...1)', default=0.3)
    args = parser.parse_args()

    '''
    # Examples

    ## Evaluate predictions with manual labels

    Compare ground-truth labels of project 5, user 5,
    with predictions in the database.

    `python evaluate.py labels -p 5 -u 5 -tf 0.4 -tp 0.3`

    ## Evaluate predictions with manual confidences

    Evaluate predictions of project 10, user 5,
    with the manual confidences.

    `python evaluate.py confidences -p 10 -u 5`
    '''

    main(args.mode, args.project_id, args.user_id, args.threshold_flowers, args.threshold_pollinators)

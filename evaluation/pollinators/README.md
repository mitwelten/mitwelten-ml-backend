# Evaluation of Flower/Pollinator Model

## Generating Model Performance Metrics

To generate the model performance metrics, use [`evaluate.py`](./evaluate.py). The script loads the ground truth data from label-studio JSON and the predictions from the database. The script can be run in two modes, `labels` and `confidences`:

`labels` evaluates predictions by comparing the ground truth data (labels created manually in [label-studio](#label-studio-import)) with the predictions, and outputs metrics in CSV format to standard output.

`confidences` evaluates predictions that were manually graded with confidences in label-studio and outputs collecive metrics as well as per class metrics to standard output.

### Usage

```bash
python evaluate.py [mode] -p [project_id] -u [user_id] -tf [threshold_flowers] -tp [threshold_pollinators]
```

The script takes the following arguments:

- `-p PROJECT_ID`: The project ID of the project in label-studio containing the ground truth data.
- `-u USER_ID`: The user ID of the user who created the ground truth data in label-studio.
- `-tf THRESHOLD_FLOWERS` and `-tp THRESHOLD_POLLINATORS`: IoU thresholds for matching the annotation rectangles.

### Examples

#### Evaluate predictions with manual labels

Compare ground-truth labels of project 5, user 5, with predictions in the database. Use a IoU threshold of 0.4 for flowers and 0.3 for pollinators.

```bash
python evaluate.py labels -p 5 -u 5 -tf 0.4 -tp 0.3
```

#### Evaluate predictions with manual confidences

Evaluate predictions of project 10, user 5, with the manual confidences.

```bash
python evaluate.py confidences -p 10 -u 5
```

### Method

#### Mode `labels`

The rectangles from the ground truth data are compared with the rectangles from
the database. They matched _if they overlap_ by more than 50% (or
custom threshold `-tf`, `-tp`) by the IoU (Intersection over Union) metric, and _if they have the same class_.

The number of matched rectangles is then compared with the number of rectangles
in the ground truth data and the number of rectangles in the database, to
calculate the number of false positives, false negatives, true positives and from those nummbers the precision, recall and F1 score.

#### Mode `confidences`

The manually added confidences are used to classify the predictions into
categories of false and true positives. Since we only evaluate predictions
and not the ground truth, we can't calculate the recall and F1 score but we can
calculate the precision of the model overall and for the specific classes.

In a further step we could compare the manual confidence with the confidence
of the model to see if the model is overconfident or underconfident.

### Input/Output

The script takes a JSON file as input (or reads the Label Studio task files from
S3 storage). The input contains the ground truth data for images. The JSON
file is expected to be in the folder [`ground_truth`](./ground_truth). The content of the JSON file is expected to contain records in the label-studio task format, containing the `file_id` of the image along with the rectangles and class in the `result` field.

For more details on data format and procedures read the docstrings for the functions `evaluate_with_groundtruth()` and `evaluate_with_confidence()` in [`evaluate.py`](./evaluate.py).

## Label-Studio Import

We evaluated the Flower/Pollinator model using the [Label-Studio](https://labelstud.io/) tool. The Label-Studio tool allows us to import images records, to be labelled manually. Also, we can import the model predictions for comparison.

### Label-Studio Project Setup

Create a new project in Label-Studio, add the configuration for the labeling interface (see [`label_config.xml`](./label-studio/label_config.xml)), and add source and target cloud-storage configurations. The source configuration should point to the S3 bucket containing the images, the target configuration should point to a S3 bucket where the labeling results can be stored (in JSON format).

### Importing Image-Records and Model Predictions

To convert the image records to the Label-Studio task format, use [`import_annotations.py`](label-studio/import_annotations.py), to convert the model predictions, use [`import_predictions.py`](label-studio/import_predictions.py).

Both scripts take a CSV file as input, which can be exported from the database using the following query (adjust the deployment IDs and time range):

```sql
select
  f.file_id, object_name, config_id,
  f.resolution[1] as o_width,
  f.resolution[2] as o_height,
  p.pollinator_id as inferrence_id,
  p.class as label,
  p.confidence as score,
  p.x0 * 100. / f.resolution[1] as x,
  p.y0 * 100. / f.resolution[2] as y,
  (p.x1 - p.x0) * 100. / f.resolution[1] as width,
  (p.y1 - p.y0) * 100. / f.resolution[2] as height
from files_image f
left join image_results ir on f.file_id = ir.file_id
left join pollinators p on ir.result_id = p.result_id
where deployment_id in (21, 49, 67)
and f.time between '2022-06-06 11:00:00+02:00' and '2022-06-06 12:00:00+02:00'
and p.class is not null
-- and p.confidence > 0.75
union all
select
  f.file_id, object_name, config_id,
  f.resolution[1] as o_width,
  f.resolution[2] as o_height,
  fl.flower_id as inferrence_id,
  fl.class as label,
  fl.confidence as score,
  fl.x0 * 100. / f.resolution[1] as x,
  fl.y0 * 100. / f.resolution[2] as y,
  (fl.x1 - fl.x0) * 100. / f.resolution[1] as width,
  (fl.y1 - fl.y0) * 100. / f.resolution[2] as height
from files_image f
left join image_results ir on f.file_id = ir.file_id
left join flowers fl on ir.result_id = fl.result_id
where deployment_id in (21, 49, 67)
and f.time between '2022-06-06 11:00:00+02:00' and '2022-06-06 12:00:00+02:00'
-- and fl.confidence > 0.75
and fl.class is not null

order by object_name;
```

Then, run the scripts to generate the Label-Studio tasks. The resulting JSON files can be uploaded the corresponding Label-Studio project.

### Importing Training/Test Data

To add the labels used to train the model, use [`import_training_set.py`](./label-studio/import_training_set.py). The script takes as input text files contained in the kaggle datasets. Download them from kaggle.com: [mitweltenflowerdataset](https://www.kaggle.com/datasets/wullti/mitweltenflowerdataset), [mitweltenpollinatordataset](https://www.kaggle.com/datasets/wullti/mitweltenpollinatordataset).

Then, run the script to generate the Label-Studio tasks:

```bash
python import_training_set.py /path/to/kaggle/dataset /output/path
```

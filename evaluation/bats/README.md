# Evaluation of Bat Detections

As part of an IP5 project, a component for labeling spectrograms in label studio is developed.
This component can be used to create ground truth data to compare the predictions of batdetect2 to.

This directory contains code to generate tasks for label studio, configuration files, etc.

## Overview of recorded data

```sql
-- overview of bat recordings in 2023
select f.deployment_id,  f.count, node_label, period, location, d.description
from (
  select extract(year from time) as year, deployment_id, count(*) as count
  from files_audio
  where sample_rate > 96000
  group by year, deployment_id
  ) as f
left join deployments d on d.deployment_id = f.deployment_id
left join nodes n on n.node_id = d.node_id
order by lower(period), node_label;
```

## Sample Data

[Deployment ID 715](https://deploy.mitwelten.org/deployment/715):

- total number of files: 34'764
- total number of detections: 10'679'964 ($\mu=0.491$, $\sigma=0.155$)
- number of classes: 17
- period: 2023-03-27 - 2023-09-29
- location: [(47.4964784,7.606228)](https://deploy.mitwelten.org/deployment/715)
- description: AM_BirsBat
- node: [4597-8048](https://deploy.mitwelten.org/node/4597-8048)

### Select Random Sample

Get a random sample of 60 files:

```sql
select file_id, object_name, time
from files_audio
where deployment_id = 715
order by random()
limit 60;
```

[bats_sample.json](./label-studio/bats_sample.json)

### Select Random Sample with Annotations

```sql
-- select random sample of files with annotations
select f.file_id, f.object_name, f.time,
r.class, r.event, r.individual, r.class_prob, r.det_prob, r.start_time, r.end_time, r.high_freq, r.low_freq
from (
  select file_id, object_name, time
  from files_audio
  where deployment_id = 715
  order by random()
  limit 60
  ) as f
left join (
  select batnet_results.* from batnet_results
  left join birdnet_tasks t on batnet_results.task_id = t.task_id
  where t.config_id = 1 and class_prob >= 0.4
) as r on r.file_id = f.file_id;
```

[bats_results_sample.json](./label-studio/bats_results_sample.json)

## Generate Tasks for Label Studio

- For empty tasks (user will add annotations manually): [import_annotations.py](./label-studio/import_annotations.py) (output: [tasks.json](./label-studio/tasks.json))
- For tasks with annotations (user will correct or confirm annotations): [import_predictions.py](./label-studio/import_predictions.py) (output: [tasks_predictions.json](./label-studio/tasks_predictions.json))

### Example Project in Label Studio

[Bats Text (Project ID 11)](https://label.mitwelten.org/projects/16/data?tab=45&task=75372) (with predictions). The template used for the labeling interface is stored in [label_config.xml](./label-studio/label_config.xml).

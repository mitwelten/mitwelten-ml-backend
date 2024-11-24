# Evaluation of BirdNET Model

We did not use label-studio to generate ground truth for training our models,
the labeling process predated the use of label-studio in our workflow.

We use label-studio to evaluate the performance of our models. For this purpose,
we created a labeling template that displays the predictions of the model and
allows the user to correct / evaluate them:

[label_config.xml](./label-studio/label_config.xml)

Another labeling template was created to demonstrate the use of a predefined
taxonomy for manually labeling audio files:

[label_config_taxonomy.xml](./label-studio/label_config_taxonomy.xml)

## Species Filters

Based on the investigetions on the data set in label-studio and based on
manual cross-checks with other data sources like [vogelwarte.ch](https://vogelwarte.ch), we created
filters for the species that may be present in the data set for a selection of
recording locations / deployments:

| deployment id | device label | group |
| ------------- | ------------ | ----- |
| 541           | 6174-3985    | FS 3  |
| 679           | 7025-1446    | FS 3  |
| 616           | 5950-1820    | FS 3  |
| 503           | 8542-0446    | FS 3  |
| 6             | 3704-8490    | FS 1  |
| 3             | 2061-6644    | FS 1  |
| 4             | 1874-8542    | FS 1  |
| 5             | 4672-2602    | FS 1  |
| 7             | 4258-6870    | FS 1  |
| 1243          | 8367-2852    | FS 2  |
| 1261          | 8537-4761    | FS 2  |

### Periods

- FS 1 2021-05-09 - 2021-06-24
- FS 2 2023-05-11 - 2023-06-26
- FS 3 2023-05-11 - 2023-06-26

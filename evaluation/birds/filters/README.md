# Bird species occurrence filters

For the most recent study, we established a set of filters to limit the BirdNET result data to a specific set of bird species.
The filters include the selection of specific deployments, specific date ranges and specific bird species.

## Deployment and date range filters

| deployment id | period start | period end | FS  |
| ------------- | ------------ | ---------- | --- |
| 541           | 2023-05-11   | 2023-06-27 | 3   |
| 679           | 2023-05-11   | 2023-06-27 | 3   |
| 616           | 2023-05-11   | 2023-06-27 | 3   |
| 503           | 2023-05-11   | 2023-06-27 | 3   |
| 6             | 2021-05-11   | 2021-06-27 | 1   |
| 3             | 2021-05-11   | 2021-06-27 | 1   |
| 4             | 2021-05-11   | 2021-06-27 | 1   |
| 5             | 2021-05-11   | 2021-06-27 | 1   |
| 7             | 2021-05-11   | 2021-06-27 | 1   |
| 1243          | 2023-05-11   | 2023-06-27 | 2   |
| 1261          | 2023-05-11   | 2023-06-27 | 2   |

## Bird species filters

The species that are to be expeced at the given locations and time periods were selected manually from our dataset of BirdNET results (inferred species).
The data is maintained in project-internal google sheets, and have been exported to this repository as TSV files ([`data`](./data/)).

## Data export

Using the script `export_filtered_data.py`, the inferences can be filtered and exported CSV files into [`export`](./export/).

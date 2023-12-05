# Inference

## Setup

```bash
sudo apt-get install ffmpeg
sudo git clone https://github.com/mitwelten/mitwelten-ml-backend.git /opt/mitwelten-ml-backend
cd /opt/mitwelten-ml-backend
sudo git submodule update --init --depth 1

# add unprivileged user to run the inferrence service
sudo adduser --system --group inferrence
sudo chown -r inferrence:inferrence /opt/mitwelten-ml-backend

# create credentials.py
cd /opt/mitwelten-ml-backend/
cp credentials-example.py credentials.py
# edit
```

Proceed to pipeline specific instructions: [BirdNET](#birdnet-pipeline-setup) / [BatNET](#batnet-pipeline-setup).

When running both pipelines, it's a good idea to let batdetect2 use the GPU and BirdNET the CPU, so each codebase
uses the more suitable hardware.

## BirdNET

### BirdNET Pipeline Setup

```bash
# install dependencies for birdnet pipeline in virtual environment
cd /opt/mitwelten-ml-backend/inferrence
sudo -u inferrence python -m venv .venv-birdnet
sudo -u inferrence /bin/bash -c 'source .venv-birdnet/bin/activate && pip install -U pip'
sudo -u inferrence /bin/bash -c 'source .venv-birdnet/bin/activate && pip install -r birdnet_pipeline/requirements.txt'

# install and start systemd service unit
sudo ln -s /opt/mitwelten-ml-backend/inference/services/mitwelten-birdnet-pipeline.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mitwelten-birdnet-pipeline.service
sudo systemctl start mitwelten-birdnet-pipeline.service
```

### Setup (local, macOS)

To get psycopg2 installed on macos arm64,
provide linker/compiler info for openssl:

```bash
export LDFLAGS="-L/opt/homebrew/opt/openssl/lib"
export CPPFLAGS="-I/opt/homebrew/opt/openssl/include"
```

Some installations (in macos) end up with version conflicts
(numpy, librosa, numba), follow this path to mitigate:

```bash
pip install numpy==1.26.6
OPENBLAS="$(brew --prefix openblas)" pip install scipy
brew install llvm@11
LLVM_CONFIG=/opt/homebrew/opt/llvm@11/bin/llvm-config pip install llvmlite==0.37.0
pip install numba==0.54.0
pip install librosa
pip install matplotlib pandas
pip install jupyterlab
```

### Running (Pipeline)

Use `birdnet_pipeline.py` to manage the task queue and run the pipeline.

To schedule tasks, you choose a batch, defined in `birdnet_runner/birdnet_batches.py`. The files matching the corresponding query
are added as tasks to the queue, referring to the batch ID. This is a crude mechanism to avoid running the same tasks
multiple times (a batch can only be added once).

```bash
# add batch with ID 7
python birdnet_pipeline.py --add-batch 7
```

In addition to the batch ID, a task refers to a configuration.
The combination of file ID, batch ID and config ID hasto be unique.
For now, a default configuration is set:

```json
{
  "random": {
    "gain": 0.23,
    "seed": 42
  },
  "overlap": 0,
  "species_list": {
    "auto": {
      "lat": 47.53774126535403,
      "lon": 7.613764385606163,
      "auto_season": false,
      "loc_filter_thresh": 0.03
    }
  },
  "model_version": "BirdNET_GLOBAL_2K_V2.1_Model_FP32"
}
```

The `model_version` refers to the base name of the tflite model file in the BirdNET repository.
From this string all other related settings are derived (mdata model, labels etc.)

The model type can't be set with this configuration because the BirdNET code doesn't allow for switching the tensorflow
implemention on the fly. This is OK because we can define the model type depending on the host architecture, depending
on wether a suitable GPU is present or not:
Set the attribute `MODEL_PATH` in [`birdnet/config.py`](./birdnet/config.py) accordingly. The pipeline worker will check
if the rest of the model version specification matches the config set in the DB.

To run the pipeline, select wether to run on GPU with the corresponding flag (`--tf-gpu`).
If the flag is absent, the pipeline runs on CPU.

Running on the GPU benefits from a batch size > 1 (set it in [`birdnet/config.py`](./birdnet/config.py)).
To suppress the verbose inferrence output of tensorflow, set `PBMODEL.predict(sample, verbose=0)` in [`birdnet/model.py`](./birdnet/model.py).

To read the input data from storage instead of S3, i.e. NFS, specify the root path with the `--source` option.

```bash
# Run the pipeline (on GPU)
python birdnet_pipeline.py --run --tf-gpu

# Read input from storage instead of S3
python birdnet_pipeline.py --run --tf-gpu --source /mitwelten
```

> _Resoning_: The model type could be read directly from [`birdnet_pipeline/birdnet/config.py`](./birdnet_pipeline/birdnet/config.py) and compared to the
> config in DB, but using the flag the choice it more explicit. By default no change in the config file is necessary, the
> BirdNET repo stays clean and no flag is required, running on CPU. Running on GPU requires a change in the BirdNET repo,
> which is confirmed by setting the `--tf-gpu` flag for the pipeline runner.

#### Pipeline process

- on `add-batch`, tasks are scheduled with file and config ID, state is set to `pending`
- idle workers pick tasks, task state is set to `running`
- on inferrence success
  - results are written to db
  - task state is set to `suceeded`
- on inferrence failure, state is set to `failed`
- on `reset-failed`, results associated to `failed` tasks are deleted, task state is set to `pending`
- on `reset-queue`, `pending` and `failed` tasks and associated results are deleted

For option reference try `python runner.py -h`

#### Task states

| state | description         |
| ----- | ------------------- |
| 0     | pending (scheduled) |
| 1     | running             |
| 2     | suceeded            |
| 3     | failed              |
| 4     | paused              |

#### Configuration options

- `species_list`: species list (one of `auto` | `db` | `file`)
  - `auto`: use BirdNET to infer species list
    - `lat`: coordinate
    - `lon`: coordinate
    - `auto_season`: infer species list from `time_start`, (if not: create year-list)
    - `loc_filter_thresh`: locaction filter threshold (0.03)
  - `db`: selection criteria
  - `file`: file path
- `overlap`: $[0, 3)$
- `random`: specs of padding noise
  - `seed`: (42)
  - `gain`: (0.3)
- `model_version`: model version, see comments above (BirdNET_GLOBAL_2K_V2.1_Model_FP32)

#### Performance / Benchmark

Hardware constraints:

- 10 CPU Cores
- 1 vGPU (NVIDIA Tesla P6-4Q), 4 GB VRAM
- 64 GB RAM
- NFS access to input

The 4 GB VRAM allow only one worker to run at a time.
The CPU model can't handle batch sizes > 1.

A few tests on a set of 20 files of 15min length yield the following results:

| platform | batchsize | n procs | avg      | total    |
| -------- | --------- | ------- | -------- | -------- |
| CPU      |         1 |       1 | 00:38.68 | 00:12:54 |
| CPU      |         1 |      10 | 01:04.24 | 00:02:19 |
| -------- | --------- | ------- | -------- | -------- |
| GPU      |         1 |       1 | 00:21.08 | 00:07:02 |
| GPU      |        32 |       1 | 00:03.06 | 00:01:01 |
| GPU      |       256 |       1 | 00:02.85 | 00:00:57 |

Even with 10 tasks running in parallel on CPU it is outperformed by the GPU with
less than half of total run time (02:19 vs. 00:57).
This will get slightly worse when running on the smaller filesize (55s), as it
sums up to 21 batches (with no overlap). Currently the inferrence takes ~330ms.

----

### Running (manual)

```bash
python birdnet_runner.py --lat 47.53774126535403 --lon 7.613764385606163 --rtype audacity
```

This will run inference on the files defined by `fileset_query` in [`birdnet_runner.py`](./birdnet_runner.py), for example (more details in [Defining datasets](#defining-datasets)):

```sql
select file_id, object_name
from birdnet_input
where node_label = '4258-6870' and duration >= 3
order by time asc
```

The results are stored in the DB, table `birdnet_results` (see [Looking at results](#looking-at-results)).
If not configured differently (by specifying `--o`), [`birdnet_runner.py`](./birdnet_runner.py) will store result files in `results/`, in the format specified in `--rtype`.

### Species List

Species lists are estimated based on location and week number as $w[1, 48]$.
The day of year can be mapped onto this type of week number as follows:

$$
w = 1 + \left\lfloor \frac {48 (d - 1)}{365} \right\rfloor
$$

```sql
select *,
  floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from birdnet_input
```

Details on the impact of week filter can be found in the corresponding [report](./reports/report_birdnet-week-filter.md).

### Issues with file size

Files larger than 1.5 GB cause the analysis process to run out of memory and crash.

### Defining datasets

Overview of dataset

```sql
create or replace view birdnet_input as
select file_id, object_name, time, file_size, sample_rate, node_label, duration, location
from files_audio f
left join nodes n on f.node_id = n.node_id
left join locations l on f.location_id = l.location_id;
grant all on table birdnet_input TO mitwelten_internal;
grant select on table birdnet_input TO mitwelten_public;

select count(*) as files,
  pg_size_pretty(sum(file_size::numeric)) as size,
  to_char(date_trunc('day', time) , 'YYYY.mm.DD') as day
from birdnet_input
where node_label = '6444-8804'
group by day
order by day;

-- the dataset
select * from birdnet_input
where node_label = '6444-8804';

-- select files which were not yet processed
select file_id, object_name
from birdnet_input i
where node_label ~ 'AM[12]' and duration >= 3 and not exists (
  select from birdnet_results o where i.object_name = o.object_name
)
order by time_start asc
```

### Looking at results

```sql
-- count results
select count(*) from birdnet_results

-- count results by species with confidence > 0.9
select count(*), species from birdnet_results where confidence > 0.9 group by species

-- show files of a species with confidence > 0.9
select * from birdnet_results where confidence > 0.9 and species = 'Acrocephalus scirpaceus' order by file_id, time_start

-- show amount total time by species
select sum(time_end-time_start) as total_time, species
from birdnet_results
where confidence > 0.7
group by species
order by total_time desc

-- example: add info from files metadata
select i.time, o.time_start, o.time_end, o.object_name, o.species, o.confidence, i.node_label
from birdnet_results o
left join birdnet_input i on i.file_id = o.file_id

-- stats by hour
select extract(hour from f.time) as t_hour, o.species, o.confidence
from results o
left join files_audio f on f.file_id = o.file_id
where o.confidence > 0.6
  and o.time_end < f.duration
```

---

## BatNET

### BatNET Pipeline Setup

```bash
# install dependencies for batnet pipeline in virtual environment
cd /opt/mitwelten-ml-backend/inferrence
sudo -u inferrence python -m venv .venv-batnet
sudo -u inferrence /bin/bash -c 'source .venv-batnet/bin/activate && pip install -U pip'
sudo -u inferrence /bin/bash -c 'source .venv-batnet/bin/activate && pip install -r batnet_pipeline/requirements.txt'

# install and start systemd service unit
sudo ln -s /opt/mitwelten-ml-backend/inference/services/mitwelten-batnet-pipeline.service /lib/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mitwelten-batnet-pipeline.service

# run the pipeline
sudo systemctl start mitwelten-batnet-pipeline.service
```

# Inference

## BirdNET

### Setup

```bash
git submodule update --init --depth 1 # clone BirdNET
sudo apt-get install ffmpeg
sudo pip install tensorflow librosa minio psycopg2
```

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

### Running

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

## Defining datasets

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

## Looking at results

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

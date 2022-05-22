# Inference

## BirdNET

### Setup

```bash
git submodule update --init --depth 1 # clone BirdNET
sudo apt-get install ffmpeg
sudo pip install tensorflow librosa minio psycopg2
```

### Running

```bash
python birdnet_runner.py --lat 47.53774126535403 --lon 7.613764385606163 --rtype audacity
```

This will run inference on the files defined by `fileset_query` in [`birdnet_runner.py`](./birdnet_runner.py), for example (more details in [Defining datasets](#defining-datasets)):

```sql
select file_id, file_path
from input_files
where device_id = '4258-6870' and duration >= 3
order by time_start asc
```

For now, these selections or runs are identified by a manually set ID (`SELECTION_ID`).

The results are stored in the DB, table `results` (see [Looking at results](#looking-at-results)).
If not configured differently (by specifying `--o`), [`birdnet_runner.py`](./birdnet_runner.py) will store result files in `results/`, in the format specified in `--rtype`.

### Species List

Species lists are estimated based on location and week number as $w[1, 48]$.
The day of year can be mapped onto this type of week number as follows:

$$
w = 1 + \left\lfloor \frac {48 (d - 1)}{365} \right\rfloor
$$

```sql
select *,
  floor((extract(doy from time_start) - 1)/(365/48.))::integer + 1 as week
from input_files
```

### Issues with file size

Files larger than 1.5 GB cause the analysis process to run out of memory and crash.

## Defining datasets

Overview of dataset

```sql
create or replace view input_files as
select file_id, file_path||file_name as file_path, time_start, file_size, sample_rate, device_id, duration, location
from files
where state = 'uploaded' and format = '1';
grant all on table public.input_files TO mitwelten_internal;
grant select on table public.input_files TO mitwelten_public;

-- ALTER TABLE IF EXISTS public.results
--     ADD COLUMN selection_id integer;
-- ALTER TABLE IF EXISTS public.results
--     ALTER COLUMN selection_id SET NOT NULL;

select count(*) as files,
  pg_size_pretty(sum(file_size::numeric)) as size,
  to_char(date_trunc('day', time_start) , 'YYYY.mm.DD') as day
from input_files
where device_id = '6444-8804'
group by date_trunc('day', time_start)
order by day;

-- the dataset
select * from input_files
where device_id = '6444-8804';

-- select files which were not yet processed
select file_id, file_path
from input_files
where device_id ~ 'AM[12]' and duration >= 3 and not exists (
  select from results where object_name = file_path
)
order by time_start asc
```

## Looking at results

```sql
-- count results
select count(*) from results where selection_id = 2

-- count results by species with confidence > 0.9
select count(*), species from results where selection_id = 2 and confidence > 0.9 group by species

-- show files of a species with confidence > 0.9
select * from results where selection_id = 2 and confidence > 0.9 and species = 'Acrocephalus scirpaceus' order by file_id, time_start

-- show amount total time by species
select sum(time_end-time_start) as total_time, species
from results
where confidence > 0.7
group by species
order by total_time desc

-- example: add info from files metadata
select files.time_start, results.time_start, results.time_end, object_name, species, confidence, device_id
from results
left join files on files.file_id = results.file_id

-- stats by hour
select extract(hour from files.time_start) as t_hour, species, confidence
from results
left join files on files.file_id = results.file_id
where confidence > 0.6
  and results.time_end < files.duration
```

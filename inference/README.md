# Inference

## Looking at results

```sql
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

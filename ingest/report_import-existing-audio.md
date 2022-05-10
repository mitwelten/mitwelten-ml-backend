# REPORT: Cleaning and import of existing audio data

## Abstract

The audio data of FS1 (2021) was collected using [Audiomoth recording devices](https://www.openacousticdevices.info/audiomoth) and stored on USB harddrives.
A naming convention for files, storage media and devices came into place only later, resulting in heterogenous path and filenames as well as duplication of files.
The aim for this import process was to __collect metadata__, __identify/remove duplicates__ and __rename the files__ adhering to one single naming convention.

## Outline

- extract metadata
- find trash
- find duplicates
- rename / reorganize files
- upload to storage
- prepare datasets

---

## Build inventory

### Indexing harddrives

```bash
# "Mitwelten HD 1"
cd /Volumes/MITWELTEN
find Auswertung -type f > mitwelten_hd_1.txt
find Heuschrecken -type f >> mitwelten_hd_1.txt
find Life\ Science -type f >> mitwelten_hd_1.txt
find Sound -type f >> mitwelten_hd_1.txt

# "Mitwelten HD small 1"
cd /Volumes/Elements
find Ei1_BirdDiversity  -type f > mitwelten_hd_small_1.txt
```

The other directories do not contain audio files.

The harddrive "Mitwelten HD 2" seems to contain similar data, it is indexed as well to make sure nothing is lost.

### Insert index to database

Read the files generated above and insert into DB with [insert_index.py](./import_existing/insert_index.py).

```bash
python insert_index.py --disk mitwelten_hd_1 mitwelten_hd_1.txt
```

This creates the record holding _original file paths_ and _source disk identifiers_

---

## Extract Metadata

It was necessary to implement some different matching patterns for the variety of path / file naming styles (see table below).
[`extract_metadata.py`](./import_existing/extract_metadata.py) implements the path name matching and extraction as well as metadata extraction from files.
The comment in the WAV file header of Audiomoth recordings contains the most important metadata: It is parsed and inserted as well.

| id | path prototype                                                      | additional data                  |
| -- | ------------------------------------------------------------------- | -------------------------------- |
| A  | Sound/FS1/fixed_AudioMoth/KW31_32/1874-8542/20210815_204501.WAV     | CONFIG.TXT, CONFIG 2.TXT , *.zip |
| B  | Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG          | -                                |
| C  | Life Science/Bats/Gundeli/Gundeli_09.2021/20210912_170000.WAV       | -                                |
| D  | Life Science/Grasshoppers/0863-3255 Villa 50 cm/20210907_193100.WAV | CONFIG.TXT, audacity projects    |
| E  | Life Science/6444-8804/20210912_112029.WAV                          | -                                |
| F  | KW20_21/2061-6644_2/20210519_212900.WAV                             | config.txt etc.                  |
| G  | AM2_KW12/20210519_212900.WAV                                        | -                                |

```bash
# for more documentation check `python extract_metadata.py -h`
python extract_metadata.py --update_raw  --disk mitwelten_hd_1 --mountpoint /Volumes/MITWELTEN --pattern F --opath "Life Science/64"
python extract_metadata.py --check_empty --disk mitwelten_hd_1 --mountpoint /Volumes/MITWELTEN
```

Main objectives:

- `import_raw`: read a selection of records and import metadata from files / file-paths
- `check_empty`: for unchecked files or ones with invalid format, check if they are empty

The comment format for recording end status changed between some Audiomoth firmware update.
Tests to ensure complete parsing by regex in [`test_rec_stat_parser.py`](./import_existing/test_rec_stat_parser.py).

---

## Find differences

Check for files that don't have same hash on both disks (mitwelten_hd_1, mitwelten_hd_2)

```sql
select count(disk) disk from files f where state = 'updated' and original_file_path like 'Sound%' group by disk

-- 228594 "mitwelten_hd_1"
-- 226914 "mitwelten_hd_2"
--   1680 -

-- 1680 duplicates on disk 1 that also exist (not as duplicates on disk 2)
select f_1.original_file_path as ofp_a, f_2.original_file_path as ofp_b, f_1.disk as disk_a, f_2.disk as disk_b, f_1.sha256, f_2.sha256 from (
  select original_file_path, disk, sha256 from files f where disk = 'mitwelten_hd_1' and state = 'updated' and original_file_path like 'Sound%'
  and not exists (
    select
    from files
    where disk = 'mitwelten_hd_2'
    and original_file_path = f.original_file_path
  )
) f_1 left join (select original_file_path, disk, sha256 from files f where disk = 'mitwelten_hd_2' and state = 'updated') f_2 on f_1.sha256 = f_2.sha256
```

## clean up invalid paths

```sql
-- mac os hidden files
update files set action = 'delete', state = 'checked' where original_file_path ~ '.+/\._[^/]+'
```

## clean up zip

| id     | path                                                              |
| -------| ----------------------------------------------------------------- |
| 225503 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211013_230000.zip |
| 225504 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211014_055900.zip |
| 225505 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211014_075900.zip |
| 225506 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211014_195900.zip |
| 225507 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211014_215900.zip |
| 225508 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211014_235900.zip |
| 225509 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211015_065900.zip |
| 225510 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211015_075901.zip |
| 225511 | Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211015_192400.zip |
| 219433 | Sound/FS1/fixed_AudioMoth/KW41/Bats/8125-0324/Archiv.zip          |

`unzip -l Sound/FS1/fixed_AudioMoth/KW41/Bats/9589-1225/20211015_192400.zip` lists files that are already present in same directory.
The same applies for `Sound/FS1/fixed_AudioMoth/KW41/Bats/8125-0324/Archiv.zip`.
The zip files can be deleted.

```sql
update files set action = 'delete', state = 'checked' where state = 'invalid format' and disk = 'mitwelten_hd_1'
and original_file_path like '%.zip'
```

the remainder are config files:

```sql
select * from files where state = 'invalid format' and disk = 'mitwelten_hd_1'
--
update files set action = 'get path info', state = 'checked' where state = 'invalid format' and disk = 'mitwelten_hd_1'
```

one is missed: `Sound/FS1/fixed_AudioMoth/KW41/4672-2602/CONFIG 2.TXT`, manually set to checked/rename. incorporating in selection regex...

delete spotlight/mac os hidden files

```sql
update files set action = 'delete', state = 'checked' where original_file_path ~ '(\.Spotlight-V100|\.fseventsd|\.DS_Store|System Volume Information)'
```

ignore Audacity projects and data

```sql
update files set action = 'ignore', state = 'checked' where original_file_path ~ '\.aup?'
```

## Files outside Sound/FS1

Contents of `Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 9589-1225 07:09:21 /Audioaufnahmen/20211015_075901.zip`

```bash
unzip "/Volumes/MITWELTEN/Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 9589-1225 07:09:21 /Audioaufnahmen/.zip" -d ~/Downloads/20211015_075901/
unzip "/Volumes/MITWELTEN/Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 9589-1225 07:09:21 /Audioaufnahmen/20211015_192400.zip" -d ~/Downloads/20211015_192400/
unzip "/Volumes/MITWELTEN/Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 9589-1225 07:09:21 /Audioaufnahmen/Archiv 13.zip" -d ~/Downloads/20211013_202900/ # naming by last file in zip, like the other zip files
unzip "/Volumes/MITWELTEN/Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 9589-1225 07:09:21 /Audioaufnahmen/Archiv 14.zip" -d ~/Downloads/20211013_205000/ # naming by last file in zip, like the other zip files
shasum -a 256 ~/Downloads/20211015_075901/*.WAV >  zip-compare.txt
shasum -a 256 ~/Downloads/20211015_192400/*.WAV >> zip-compare.txt
shasum -a 256 ~/Downloads/20211013_202900/*.WAV >> zip-compare.txt
shasum -a 256 ~/Downloads/20211013_205000/*.WAV >> zip-compare.txt
```

and

```sql
select original_file_path,state,sha256 from files where disk = 'mitwelten_hd_1' and original_file_path ~ '20211015_07\d+\.WAV' order by original_file_path
select original_file_path,state,sha256 from files where disk = 'mitwelten_hd_1' and original_file_path ~ '20211015_1\d+\.WAV' order by original_file_path
select original_file_path,state,sha256 from files where disk = 'mitwelten_hd_1' and original_file_path ~ '20211013_20\d+\.WAV' order by original_file_path
```

100% match (proof in [`zip-compare.txt`](./import_existing/zip-compare.txt))

The zip files don't contain missing data, everything is present in `Sound/FS1`. The zip files can be deleted.

```sql
update files set action = 'delete', state = 'checked' where action = 'check zip'
```

This probably means that the files in `Auswertung/Auswertung Fledermausrufe/Analyse Marco/*/Audioaufnahmen/` are duplicates of files in `Sound/FS1/fixed_AudioMoth/KW41/Bats/`.

### proposition

- find and apply renaming scheme for files in `Sound/FS1/`
- (replace references in projects in `Auswertung/Auswertung Fledermausrufe/Analyse Marco/` with updated paths)
- replacing the references might not be necessary, batscope seems to keep a copy of the audiodata in the project file, although cut into segments (sequences)
- delete audio files and zip files in `Auswertung/Auswertung Fledermausrufe/Analyse Marco/*/Audioaufnahmen/`

Considering upload of bat recording to minIO storage:

- check if all files are duplicates
- if so: only upload content of `Sound/FS1/`

```sql
-- show non-duplicates that don't exist in auswertung
select fs1.fp, fs1.state, ausw.state, ausw.fp from (
  select original_file_path as fp, sha256 as hash, state from files
  where disk = 'mitwelten_hd_1' and action != 'delete' and state != 'empty audio' and original_file_path ~ '^Sound/FS1/fixed_AudioMoth/.+/Bats/'
) fs1
full outer join (
  select original_file_path as fp, sha256 as hash, state from files
  where disk = 'mitwelten_hd_1' and action != 'delete' and state != 'empty audio' and original_file_path ~ '^Auswertung/'
) ausw on fs1.hash = ausw.hash
where ausw.state is null
```

There are 7110 files in `Sound/FS1/fixed_AudioMoth/.+/Bats/` that don't exist in `Auswertung/Auswertung Fledermausrufe/Analyse Marco/*/Audioaufnahmen/`

mark audio-files in `Auswertung/Auswertung Fledermausrufe/Analyse Marco/*/Audioaufnahmen/` as duplicated, and to be ignored

```sql
update files f set comment = 'bats, duplicate', action = 'ignore'
where disk = 'mitwelten_hd_1'
  and action != 'delete'
  and state != 'empty audio'
  and original_file_path ~ '^Auswertung/'
  and exists (
    select
    from files
    where disk = 'mitwelten_hd_1'
      and state = 'updated'
      and original_file_path ~ '^Sound/FS1/fixed_AudioMoth/.+/Bats/'
      and sha256 = f.sha256
  )
```

Similar procedure for audio-files in `Sound/FS1/fixed_AudioMoth/.+/Bats/`, but for now, just set the comment `'dataset: bats auswertung mg'`

```sql
-- check for duplicates inside the bats dataset
select count(sha256) as dblcount from files where disk = 'mitwelten_hd_1' and comment = 'dataset: bats auswertung mg' group by sha256 order by dblcount

-- inspect the duplicates
-- '9589-1225/\d\d:\d\d:\d\d' vs '9589-1225/2021'
select original_file_path from files f where disk = 'mitwelten_hd_1' and comment = 'dataset: bats auswertung mg' and original_file_path ~ '9589-1225/\d\d:\d\d:\d\d'
and exists ( -- also check with 'not' that there aren't any leftovers
  select
  from files
  where disk = 'mitwelten_hd_1'
  and original_file_path ~ '9589-1225/2021'
  and sha256 = f.sha256
)

-- mark duplicates
update files set action = 'ignore', comment = 'dataset: bats auswertung mg, duplicate'
where disk = 'mitwelten_hd_1' and comment = 'dataset: bats auswertung mg' and original_file_path ~ '9589-1225/\d\d:\d\d:\d\d'

-- more duplicates to be found:
-- 'Bats/MG \d\d:\d\d:\d\d' vs 'Bats/\d\d\d\d[-_]\d\d\d\d/2021'
select count(original_file_path) from files f
-- Sound/FS1/fixed_AudioMoth/KW43/Bats/MG 26:10:22 8125-0324/20211027_064800.WAV
where disk = 'mitwelten_hd_1' and comment = 'dataset: bats auswertung mg' and original_file_path ~ 'Bats/MG \d\d:\d\d:\d\d'
and not exists (
  select
  from files
  where disk = 'mitwelten_hd_1'
  and original_file_path ~ 'Bats/\d\d\d\d[-_]\d\d\d\d/2021'
  and sha256 = f.sha256
)

-- mark duplicates
update files set action = 'ignore', comment = 'dataset: bats auswertung mg, duplicate'
where disk = 'mitwelten_hd_1' and comment = 'dataset: bats auswertung mg' and original_file_path ~ 'Bats/MG \d\d:\d\d:\d\d'
```

Then, the number of files in `Auswertung` doesn't match the ones in the dataset. Finding even more duplicates in `Auswertung`:

```sql
-- show paths with duplicate hashes
with bats as (select file_id, original_file_path, sha256 from files where comment = 'bats, duplicate')
select files_a.original_file_path as f_a, files_b.original_file_path as f_b from bats files_a
left join bats files_b on files_a.sha256 = files_b.sha256 and files_a.file_id <> files_b.file_id
where files_b.original_file_path is not null
order by files_a.original_file_path

-- compare differences in file meta info
select device_id, serial_number from files where original_file_path = 'Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 0863-3235 25:10:21/Audioaufnahmen/20211025_225900.WAV'
-- "0863-3235"  "24F319055FDF2902" -- 20211025_225900.WAV date is 25.10
-- "8125-0324"  "24F319055FDF2902" -- 20211025_225900.WAV date is 25.10, but filed in Bats MG 8125-0324 24:10:21. this must be the wrong one
select device_id, serial_number from files where original_file_path = 'Auswertung/Auswertung Fledermausrufe/Analyse Marco/Bats MG 8125-0324 24:10:21 /Audioaufnahmen/20211025_225900.WAV'

-- check the matches (540, this corresponds to the previous findings)
select original_file_path, comment from files where device_id = '8125-0324' and serial_number = '24F319055FDF2902'

-- mark accordingly
update files set comment = 'bats, double duplicate, 8125-0324 inst of 0863-3235'  where device_id = '8125-0324' and serial_number = '24F319055FDF2902'

-- check if now the number of correct files in `Sound/FS1/fixed_AudioMoth/.+/Bats/` and `Auswertung/Auswertung Fledermausrufe/Analyse Marco/*/Audioaufnahmen/` is the same
select (select count(disk) from files where comment = 'bats, duplicate') = (select count(disk) from files where comment = 'dataset: bats auswertung mg')
```

Finding the remaining duplicates

```sql
select count(sha256) from files where state = 'updated' and action != 'ignore' and disk = 'mitwelten_hd_1' group by sha256 having count(sha256) > 1
-- 2362 duplicates remain

create temp table dup_hash as
select sha256 from files where state = 'updated' and action != 'ignore' and disk = 'mitwelten_hd_1' group by sha256 having count(sha256) > 1

select original_file_path, sha256 from files
where state = 'updated' and action != 'ignore' and disk = 'mitwelten_hd_1'
  and exists (select from dup_hash where dup_hash.sha256 = files.sha256)
  and original_file_path ~ 'KW(?:34_35|36_37)/1874-8542'
order by original_file_path desc -- and asc to find the first
```

There seem to be duplicates in `KW34_35` and `KW36_37`:

- KW34_35
  - Sound/FS1/fixed_AudioMoth/__KW34_35__/1874-8542/__20210906_134501__.WAV -> kw36
  - Sound/FS1/fixed_AudioMoth/__KW34_35__/1874-8542/__20210913_222255__.WAV -> kw37
- KW36_37
  - Sound/FS1/fixed_AudioMoth/__KW36_37__/1874-8542/__20210906_134501__.WAV -> kw36
  - Sound/FS1/fixed_AudioMoth/__KW36_37__/1874-8542/__20210913_222255__.WAV -> kw37

The files in `KW34_35` should be ignored and marked as duplicate

```sql
update files set action = 'ignore', comment = 'duplicate'
where state = 'updated' and action != 'ignore' and disk = 'mitwelten_hd_1'
and exists (select from dup_hash where dup_hash.sha256 = files.sha256)
and original_file_path ~ 'KW34_35/1874-8542'

drop table dup_hash
```

Result: 224 GB of data ignored on 'mitwelten_hd_1'

| size    | count  | action        | state       |
| ------- | ------ | ------------- | ----------- |
|         | 4666   | delete        | checked     |
|         | 38     | get path info | checked     |
|         | 88     | ignore        | checked     |
|         | 56615  | ignore        | empty audio |
| 224 GB  | 10101  | ignore        | updated     |
| 2315 GB | 301246 | rename        | updated     |

`select pg_size_pretty(sum(file_size)), count(disk), action, state from files where disk = 'mitwelten_hd_1' group by action, state`

## Update text file records

```sql
update files
set format = 'text',
  device_id = substring(original_file_path from '/(?:KW[^/]+)(?:/Bats)?/(\d\d\d\d[-_]\d\d\d\d)'),
  week = substring(original_file_path from '/(KW[^/]+)(?:/Bats)?/(?:\d\d\d\d[-_]\d\d\d\d)')
WHERE action = 'get path info'
ORDER BY original_file_path ASC
```

## check difference between hd1 and hd2

```sql
create temp table hd1 as
select original_file_path as ofp, sha256 as hash, serial_number as sn, device_id as did, sample_rate as sr
from files
where disk = 'mitwelten_hd_1' and format = '1' and action = 'rename' and original_file_path not like 'Life Science%';

create temp table hd2 as
select original_file_path as ofp, sha256 as hash, serial_number as sn, device_id as did, sample_rate as sr
from files
where disk = 'mitwelten_hd_2' and format = '1' and action = 'rename';

select (select count(ofp) from hd1) = (select count(ofp) from hd2);

-- also check that the hashes match
select ofp from hd2 where not exists (select from hd1 where hd1.hash = hd2.hash);
select ofp from hd1 where not exists (select from hd2 where hd1.hash = hd2.hash);

drop table hd1;
drop table hd2;
```

## Summary

- `mitwelten_hd_2` ignored, content identical to `mitwelten_hd_1`
- `mitwelten_hd_1` and `mitwelten_hd_small_1` indexing complete, result below

| size    | count  | action        | state       |
| ------- | ------ | ------------- | ----------- |
| 0       | 120111 | ignore        | empty audio |
| 224 GB  | 10102  | ignore        | updated     |
| 4091 GB | 610189 | rename        | updated     |

---

## Coordinates

Some of the coordinates are in swiss grid format _LV95_ (1903+), others in _WGS84_. Transformation at [swisstopo](https://www.swisstopo.admin.ch/en/maps-data-online/calculation-services/navref.html). Convert to decimal degress (`[°]`, not deg/min/sec).

A collection of audiomoths' coordinates is found in [fs1ei0.kml](https://raw.githubusercontent.com/mitwelten/mitwelten.github.io/master/fs1/fs1ei0.kml) in the mitwelten.github.io repo.

The question is now: __Which audiomoths / device_id (SD card ID) were used at which coordinates at what time?__

```py
# pip install pykml
from urllib import request
from pykml import parser
r = request.urlopen('https://raw.githubusercontent.com/mitwelten/mitwelten.github.io/master/fs1/fs1ei0.kml')
root = parser.parse(r).getroot()
for device in root.Document.Placemark:
  coord = device.Point.coordinates.text.split(',')
  print(device.get('id').split('_')[1], f'{coord[1]}, {coord[0]}', sep=';')
```

| device_id | coordinates [° lat,lon]              |
| --------- | ------------------------------------ |
| 3704-8490 | 47.534649, 7.613092                  |
| 2061-6644 | 47.534230, 7.614490                  |
| 1874-8542 | 47.535135, 7.614674                  |
| 4672-2602 | 47.536054, 7.614804                  |
| 4258-6870 | 47.538413, 7.615415                  |
| 6444-8804 | 47.5612038295474, 7.591551112713341  |
| 6431-2987 | 47.54329652492795, 7.596164727046104 |

Longitude 7.614490083
Latitude: 47.534230119

## Add new, synthetic device ID

While adding the device id from the "SNF Mitwelten Inventory" I noticed that there were already files with the same start time and device ID.
It appears two SD-cards with the same ID have been used at the same time.
I set the device_id of the previously unlabelled files from `6431-2987` to `3164-8729` by switching pairs of numbers.

```sql
update files
set device_id = '3164-8729'
where original_file_path ~ 'Life Science/Bats/Gundeli/Gundeli.+' and format = '1' and action = 'rename'
```

## Find files unique files per disk

```sql
-- files that only exist on small_1
select * from files f where disk='mitwelten_hd_small_1' and not exists (
  select
  from files
  where disk = 'mitwelten_hd_1'
  and sha256 = f.sha256
)

select * from files f where disk='mitwelten_hd_2' and sha256 is not null and not exists (
  select
  from files
  where disk = 'mitwelten_hd_1'
  and sha256 = f.sha256
)
```

## Mark backups

```sql
update files f
set state = 'backup', action = 'keep'
where (disk='mitwelten_hd_small_1' or disk='mitwelten_hd_2') and sha256 is not null and exists (
  select
  from files
  where disk = 'mitwelten_hd_1'
  and sha256 = f.sha256
)
```

---

## Rules for renaming

- move CONFIG files into top level directory where it applies
- rename `config.txt` that are `format = 'json'` to config.json
- rename `CONFIG 2.txt` to `CONFIG.txt` (hd1 `file_id = 226809`)

`device-id / date / hour / device-id_timestamptz.ext`

`0000-0000 / yyyy-mm-dd / HH / 0000-0000_yyyy-mm-ddThh-mm-ssZ.ext`

Apply the renaming rule for audio files

```sql
update files
set
  file_name = device_id||'_'||to_char(time_start at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||'.wav',
  file_path = device_id||'/'||to_char(time_start at time zone 'UTC', 'YYYY-mm-DD/HH24/')
where format = '1'
  and action = 'rename'
```

Check that there are no duplicate filenames

```sql
select file_name
from files
where format = '1' and action = 'rename' and (disk='mitwelten_hd_1' or disk='mitwelten_hd_small_1')
group by file_name
having count(file_name) > 1
order by file_name
```

Get the set of files to rename

```sql
select disk, original_file_path, file_path, file_name
from files
where action = 'rename' and format = '1'
```

| size    | filecount | disk                 |
| ------- | --------- | -------------------- |
| 2315 GB | 301246    | mitwelten_hd_1       |
| 1716 GB | 296593    | mitwelten_hd_small_1 |
| __4031 GB__ | __597839__ | __total__       |

---

## Upload to minIO storage

[`upload.py`](./import_existing/upload.py) is a multithreaded minIO uploader for all the files marked for upload.
Records of successfully uploaded files are marked accordingly, failed uploads as well.

The mountpoint of the disk is read from a lookup table, matching to the argument `--disk`.

---

## Corrections

```sql
-- triage of active periods per device and card
select serial_number, device_id, min(time_start) as dev_start, max(time_start) as dev_end
--, substring(original_file_path from '(.+)/[^/]+') as fpath
from files where time_start > timestamptz '2000-01-05 02:19:24+01' and format = '1' and (action = 'rename' or state = 'uploaded') group by serial_number, device_id order by dev_start

select substring(original_file_path from '(.+)/[^/]+') as fpath, min(time_start) as dev_start, max(time_start) as dev_end, device_id
from files where device_id = '4258-6870' or device_id = '4285-6870'
group by fpath, device_id order by dev_start

select device_id, count(file_name), pg_size_pretty(sum(file_size::numeric))
from files where state = 'uploaded' and device_id ~ '42(85|58)-6870' group by device_id

select device_id, count(file_name), pg_size_pretty(sum(file_size::numeric))
from files where state = 'uploaded' and device_id ~ '0863-32[35]5' group by device_id
```

- device_ids `4258-6870` and `4285-6870` can be consolidated to `4258-6870`
- device_ids `0863-3235` and `0863-3255` can be consolidated to `0863-3235` or `0863-3255`, __after checking that there is no sd card labelled one or the other way__!

### Rename `4285-6870` to `4258-6870`

- delete from minio storage: `4285-6870`
- change `device_id` to `4258-6870`
- recreated `file_name` and `file_path`
- upload to minio storage

```sql
update files set device_id = '4258-6870', update_at = now(), action = 'reupload' where device_id = '4285-6870';
update files
set
  file_name = device_id||'_'||to_char(time_start at time zone 'UTC', 'YYYY-mm-DD"T"HH24-MI-SS"Z"')||'.wav',
  file_path = device_id||'/'||to_char(time_start at time zone 'UTC', 'YYYY-mm-DD/HH24/'),
  updated_at = now()
where action = 'reupload'
```

## Add change tracking columns

- Add the fields `created_at` and `updated_at` to table `mitwelten`
- Update all records, setting both fields
- Add `NOT NULL` constraint to both fields
- modify `INSERT` and `UPDATE` queries everywhere

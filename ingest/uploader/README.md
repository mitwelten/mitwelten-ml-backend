# Mitwelten File Uploader

## Credentials

To run the app or cli, you need to store the PostgreSQL and minIO credentials in a
file `./credentials.py` (see [`credentials_example.py`](../../credentials_example.py)).

## Upload Image Files (manual)

Use the cli [`uploader_cli.py`](./uploader_cli.py) to upload image files recorded by RaspberryPi cameras.

The files are required to follow the format `<node_id>_<utc timestamp>.jpg`.

The cli import and checks the metadata:

- Is the file a valid JPEG image file?
- Are there duplicates (identical content and/or file name) in the files you want to upload?
- Are the files alredy existing in storage/db?

Only files with valid, unique content that don't create file name collisions will be uploaded.

```bash
# example:
pip install -r requirements.txt
python uploader_cli.py --threads 8 /Volumes/SDCARD/
```

This CLI will eventually be updated to also upload other types of media.

## Upload Image Files (on field nodes, automated)

Image Files captures by deployed nodes can be ingested directly from the node by user the `uploader_node` distribution.
The upload process is challenging as it has to account for very low bandwith and limited system resources.
The distribution consists of a python script with configuration and 3 System-D service units.

### Setup

- Clone this repo onto the node
- Install python venv and dependencies
- Install and start the System-D service units

For details check [services/README.md](./services/README.md)

### Running

The system services `img-indexer`, `img-metadata` and `img-uploader` are running in parallel.
The schedule is set by time ranges in `uploader_node_config.py`.
To avoide excessive load / heat on the node, metadata extraction and uploads should run when image caputre is not
running, ideally at night.

The tracking of file states revolves around metadata stored in a local sqlite database (`file_index.db`).
This database contains an index of all files ever processed on a specific node and holds a [state](#filetask-states),
the sha256 hash, image metadata and process timestamps.

#### Index Paths

```mermaid
flowchart TD
  index[[index paths]] --> checkpoint(get checkpoint)
  checkpoint -->  build_file_list

  subgraph build_file_list [loop: build file list]
    cp_older{"younger<br> than<br> checkpoint"}
    get_path(read path<br>from filesystem) --> cp_older --no--> ignore
    cp_older --yes--> path_unique
    path_unique{path unique}
    path_unique --no--> ignore
    path_unique --yes--> is_not_hidden{not hidden}
    is_not_hidden --yes--> is_jpeg{JPEG}
    is_not_hidden --no--> ignore
    is_jpeg --yes--> add_to_index[add to db, state = 0]
    is_jpeg --no--> ignore
  end

  build_file_list --> update_checkpoint(update checkpoint)
  update_checkpoint --> wait(wait for next iteration)
```

----

#### Extract Metadata

```mermaid
flowchart TD

  extract_meta[[extract metadata]]

  subgraph meta_loop [meta extraction loop]

    get_state_0(get file, state = 0)

    subgraph check_corruption [check image corruption]
      direction LR
      img.verify(PIL verify)
      img.transpose("PIL transpose<br>(read all pixels)")
    end

    subgraph get_meta [extract metadata]
      direction LR
      get_resolution(get resolution)
      get_sha256(get sha256 hash)
      get_file_size(get file size)
      get_timestamp(parse timestamp<br>from filename)
    end

    meta_success{extract<br>success}
    hash_unique{hash<br>unique}
    set_state_1[state = 1]
    set_state_-1[state = -1]
    set_state_-2[state = -2]
  end
  wait_meta(wait for next iteration)

  extract_meta --> meta_loop

  img.verify --> img.transpose

  get_resolution -->
  get_sha256 -->
  get_file_size -->
  get_timestamp

  get_state_0 --> check_corruption --> get_meta --> meta_success

  meta_success --no--> set_state_-1
  meta_success --yes--> hash_unique

  hash_unique --no--> set_state_-2
  hash_unique --yes--> set_state_1

  meta_loop --> wait_meta
```

----

#### Upload File and Metadata

```mermaid
flowchart TD

upload[[upload file and metadata]]

subgraph queue [mark file as queued]
  direction LR
  get_state_1(get file, state = 0)
  set_state_3["state = 3<br>(queued)"]
end

subgraph check [check server connections]
  direction LR
  check_s3_connection(check S3 connection)
  check_api_connection(check API connection)
end


subgraph validate [validate against database]
  validate_image_db(validate metadata<br>against records database)
  hash_object_unique_db{hash and<br>object name<br>unique}
  set_state_-3["state = -3<br>(remote duplicate)"]
  node_deployed{node deployed}
  set_state_-6["state = -6<br>(node not deployed)"]
end

subgraph upload_s3 [upload file to S3 storage]
  file_exists{file readable}
  set_state_-7["state = -7<br>(local file read error)"]
  upload_file(upload to storage)
  upload_success{upload<br>successful}
  set_state_-4["state = -4<br>(storage upload failed)"]
  set_state_2["state = 2<br>(uploaded to storage)"]
end

subgraph insert_meta [upload metadata to db]
  upload_api(upload meta to database)
  upload_api_success{upload meta<br>successful}
  set_state_-5["state = -5<br>(meta upload failed)"]
end

subgraph delete_local [delete file locally]
  delete(delete)
  set_state_4["state = 4<br>(upload process successful)"]
end

upload -->
queue -->
check -->
validate
upload_s3
insert_meta
delete_local

get_state_1 --> set_state_3

check_s3_connection --> check_api_connection

validate_image_db --> hash_object_unique_db
hash_object_unique_db --yes---> node_deployed
hash_object_unique_db --no--> set_state_-3
node_deployed --yes---> file_exists
node_deployed --no--> set_state_-6

file_exists --yes---> upload_file
file_exists --no--> set_state_-7

upload_file --> upload_success

upload_success --yes---> set_state_2 --> upload_api
upload_success --no--> set_state_-4

upload_api -->
upload_api_success --yes---> delete
upload_api_success --no--> set_state_-5

delete --> set_state_4
```

----

### File/Task states

| state | description
| ----- | -----------
|     0 | indexed, new
|       | __error states__
|    -1 | corruption check / meta extraction failed (move)
|    -2 | duplicate hash/object-name locally (delete)
|    -3 | duplicate hash/object-name in database (check if exists in s3 then delete warn and keep)
|    -4 | file upload error
|    -5 | failed to insert metadata in db
|    -6 | node is/was not deployed at requested time
|    -7 | file not found locally
|       | __success states__
|     1 | checked, no local duplicate, file intact
|     2 | upload successful
|     3 | scheduled for upload / upload running
|     4 | deleted locally after successful upload
|     5 | moved corrupted
|    42 | paused

### Maintenance

__Corrupted files__ (state -1) can be moved to a dedicated directory (`/mnt/elements/corrupted/`) for manual inspection.
This command sets `state = 5` once a file is moved.

```bash
python uploader_node.py --move-corrupted
```

Files can fail validation with __duplicate hash in DB__ (state -3) when an upload is retried after previous upload failed or the process was otherwhise interrupted.
These files can be rechecked to make sure they exists in storage, if so they will be deleted locally.
This command sets `state = 4` if the file exists in storage and is deleted locally.

```bash
python uploader_node.py --check-metadupes
```

Files that locally have a __duplicate hash__ (state -2, duplicate content) can be safely deleted.
This state is extremely rare an has no implementation to act on it.

Files that remain in local storage were skipped by the indexing process because the path already existed in the local db.
They can be safely deleted __after a complete index scan__ (the incremental indexing is not 100% safe yet).

## Upload Audio Files

Use the app to upload audiofiles recorded by Audiomoths.
The app imports and checks the metadata from the recorded audio:

- Does the file contain audio (in the correct format)?
- Is the file empty?
- Would there be name collisions in the filename / path with the already existing files?
- Are there files with identical content?

Only audiofiles with valid, unique content that don't create file name collisions will be uploaded.

### HowTo

- Insert SD-Card
- Start the app
- Select the ID printed on the SD-Card from the dropdown menu
- Click "Import Metadata" to select the path to the SD-Card
- _Check if the metadata matches your expectations_
- Click "Upload Audiofiles" to upload the valid files to storage

### Build on macOS / Windows

```bash
pip install -r requirements.txt
pyinstaller mitwelten_uploader_app.spec
```

# Mitwelten File Uploader

## Credentials

To run the app or cli, you need to store the PostgreSQL and minIO credentials in a
file `credentials.py` (see [`credentials_example.py`](../../credentials_example.py)).

## Upload Image Files

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

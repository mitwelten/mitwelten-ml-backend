# Mitwelten Audio Uploader

Use this app to upload audiofiles recorded by Audiomoths.
The app imports and checks the metadata from the recorded audio:

- Does the file contain audio (in the correct format)?
- Is the file empty?
- Would there be name collisions in the filename / path with the already existing files?
- Are there files with identical content?

Only audiofiles with valid, unique content that don't create file name collisions will be uploaded.

## HowTo

- Insert SD-Card
- Start the app
- Select the ID printed on the SD-Card from the dropdown menu
- Click "Import Metadata" to select the path to the SD-Card
- _Check if the metadata matches your expectations_
- Click "Upload Audiofiles" to upload the valid files to storage

## Credentials

To run the app, you need to store the PostgreSQL and minIO credentials in a
file `credentials.py` (see [`credentials_example.py`](credentials_example.py)).

## Build on macOS / Windows

```bash
pip install -r requirements.txt
pyinstaller mitwelten_uploader_app.spec
```

# Mitwelten Audio Uploader

## Credentials

To run the app, you need to store the PostgreSQL and minIO credentials in a
file `credentials.py` (see [`credentials_example.py`](credentials_example.py)).

## Build on macOS / Windows

```bash
pip install -r requirements.txt
pyinstaller mitwelten_uploader_app.spec
```

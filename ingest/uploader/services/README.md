# System D Service Units

## Installation

### Setup venv and install dependencies

```bash
UPLOADERDIR="$HOME/mitwelten-ml-backend/ingest/uploader"

cd $UPLOADERDIR
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-uploader-node.txt
```

### Check paths

Check if the paths are correctly setup in the system units.

All units:

- `WorkingDirectory`: Absolute path to `ingest/uploader/` in this repo
- `ExecStart`: Absolute path to `ingest/uploader/.venv/bin/python` in this repo

`mitwelten-img-indexer.service`:

- `ExecStart`: The option `--index` with absolute path to __root capture directory__

### Install and start system units

```bash
UPLOADERDIR="$HOME/mitwelten-ml-backend/ingest/uploader"

# enable lingering (start user units w/o login)
sudo loginctl enable-linger $USER

# install system units
mkdir -p $HOME/.config/systemd/user
ln -s $UPLOADERDIR/services/mitwelten-img-indexer.service $HOME/.config/systemd/user/
ln -s $UPLOADERDIR/services/mitwelten-img-metadata.service $HOME/.config/systemd/user/
ln -s $UPLOADERDIR/services/mitwelten-img-uploader.service $HOME/.config/systemd/user/

# enable the units
systemctl --user daemon-reload
systemctl --user enable mitwelten-img-indexer.service
systemctl --user enable mitwelten-img-metadata.service
systemctl --user enable mitwelten-img-uploader.service

# start the units
systemctl --user start mitwelten-img-indexer.service
systemctl --user start mitwelten-img-metadata.service
systemctl --user start mitwelten-img-uploader.service
```

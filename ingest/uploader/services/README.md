# System D Service Units

## mitwelten-img-index.service

First, check if the paths are correctly setup in the system unit `mitwelten-img-indexer.service`.
Then install and start:

```bash
UPLOADERDIR="$HOME/mitwelten-ml-backend/ingest/uploader"

cd $UPLOADERDIR
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-uploader-node.txt

# enable lingering (start user units w/o login)
sudo loginctl enable-linger $USER

# install system unit
mkdir -p $HOME/.config/systemd/user
ln -s $UPLOADERDIR/services/mitwelten-img-indexer.service $HOME/.config/systemd/user/

# enable the unit
systemctl --user daemon-reload
systemctl --user enable mitwelten-img-indexer.service

# start the unit
systemctl --user start mitwelten-img-indexer.service
```

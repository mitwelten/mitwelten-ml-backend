# System D Service Units

## Installation

### Install dependencies

```bash
# (un)install prometheus and dependencies
sudo apt update -y
sudo apt install -y prometheus-node-exporter
sudo systemctl stop exim4.service
sudo systemctl disable exim4.service
sudo systemctl stop smartd.service
sudo systemctl disable smartd.service
sudo systemctl stop prometheus-node-exporter-smartmon.timer
sudo systemctl disable prometheus-node-exporter-smartmon.timer
sudo systemctl stop prometheus-node-exporter-apt.timer
sudo systemctl disable prometheus-node-exporter-apt.timer
sudo systemctl stop prometheus-node-exporter-ipmitool-sensor.timer
sudo systemctl disable prometheus-node-exporter-ipmitool-sensor.timer
sudo systemctl stop prometheus-node-exporter-mellanox-hca-temp.timer
sudo systemctl disable prometheus-node-exporter-mellanox-hca-temp.timer

UPLOADERDIR="$HOME/mitwelten-ml-backend/ingest/uploader"

cd $UPLOADERDIR
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements-uploader-node.txt
```

### Check paths / configuration

Check if the paths are correctly setup in the system units.

All units:

- `WorkingDirectory`: Absolute path to `ingest/uploader/` in this repo
- `ExecStart`: Absolute path to `ingest/uploader/.venv/bin/python` in this repo

`mitwelten-img-indexer.service`:

- `ExecStart`: The option `--index` with absolute path to __root capture directory__

`mitwelten-exporter.service`:

- make sure the `--metrics-path` exists and is writable (`mkdir ~/monitoring`)
- configure `prometheus-node-exporter` with the corresponing path and port number (`xxxx`):

```bash
echo 'ARGS="--web.listen-address=\":9958\" --collector.textfile.directory=\"/home/pi/monitoring/\""' \
  | sudo tee --append /etc/default/prometheus-node-exporter
```

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
ln -s $UPLOADERDIR/services/mitwelten-exporter.service $HOME/.config/systemd/user/

# enable the units
sudo systemctl enable prometheus-node-exporter.service
systemctl --user daemon-reload
systemctl --user enable mitwelten-img-indexer.service
systemctl --user enable mitwelten-img-metadata.service
systemctl --user enable mitwelten-img-uploader.service
systemctl --user enable mitwelten-exporter.service

# start the units
sudo systemctl start prometheus-node-exporter.service
systemctl --user start mitwelten-img-indexer.service
systemctl --user start mitwelten-img-metadata.service
systemctl --user start mitwelten-img-uploader.service
systemctl --user start mitwelten-exporter.service
```

## Monitoring

`mitwelten-exporter` depends on `prometheus-node-exporter` to read and expose the metrics to the prometheus server.
In order to read metrics from `prometheus-node-exporter`, the corresponding port (see above) needs to be accessible,
which requires a yaler tunnel.

# System D Service Units

## mitwelten-img-index.service

First, check if the paths are correctly setup in the system unit `mitwelten-img-uploader.service`.
Then install and start:

```bash
# enable lingering (start user units w/o login)
sudo loginctl enable-linger $USER

# install system unit
mkdir -p $HOME/.config/systemd/user
ln -s $HOME/upload/mitwelten-img-indexer.service $HOME/.config/systemd/user/

# enable the unit
systemctl --user daemon-reload
systemctl --user enable mitwelten-img-uploader.service

# start the unit
systemctl --user start mitwelten-img-uploader.service
```

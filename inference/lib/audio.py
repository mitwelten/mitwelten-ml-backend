import numpy as np

from io import BytesIO
import librosa

import config as cfg
import credentials as crd

import psycopg2 as pg
from minio import Minio

RANDOM = np.random.RandomState(cfg.RANDOM_SEED)

def openAudioFile(object_name, sample_rate=48000, offset=0.0, duration=None):

    client = Minio(
        crd.minio.host,
        access_key=crd.minio.access_key,
        secret_key=crd.minio.secret_key,
    )

    try:
        response = client.get_object(crd.minio.bucket, object_name)
        audio_data = BytesIO(response.read())
        sig, rate = librosa.load(audio_data, sr=sample_rate, offset=offset, duration=duration, mono=True, res_type='kaiser_fast')
    except:
        sig, rate = [], sample_rate
    finally:
        response.close()
        response.release_conn()

    return sig, rate

def saveSignal(sig, fname):

    import soundfile as sf
    sf.write(fname, sig, 48000, 'PCM_16')

def noise(sig, shape, amount=None):

    # Random noise intensity
    if amount == None:
        amount = RANDOM.uniform(0.1, 0.5)

    # Create Gaussian noise
    try:
        noise = RANDOM.normal(min(sig) * amount, max(sig) * amount, shape)
    except:
        noise = np.zeros(shape)

    return noise.astype('float32')

def splitSignal(sig, rate, seconds, overlap, minlen):

    # Split signal with overlap
    sig_splits = []
    for i in range(0, len(sig), int((seconds - overlap) * rate)):
        split = sig[i:i + int(seconds * rate)]

        # End of signal?
        if len(split) < int(minlen * rate):
            break

        # Signal chunk too short?
        if len(split) < int(rate * seconds):
            split = np.hstack((split, noise(split, (int(rate * seconds) - len(split)), 0.5)))

        sig_splits.append(split)

    return sig_splits

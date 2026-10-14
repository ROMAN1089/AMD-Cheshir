"""Local English ASR fallback for the event gateway's missing audio capability."""
import os
import hashlib
import threading
from pathlib import Path
import amd
import store
import requests
import wave
import numpy as np

_model=None
_lock=threading.Lock()

def model_directory():
    return Path(os.getenv('ASR_MODEL_PATH') or str(store.ROOT/'data'/'models'/'tiny.en'))

def ready():
    return (model_directory()/'model.bin').exists()

def local_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        directory=model_directory()
        if not (directory/'model.bin').exists():
            directory.mkdir(parents=True,exist_ok=True)
            # Pinned public model revision; direct HTTPS avoids an unavailable Xet transport.
            revision='0d3d19a32d3338f10357c0889762bd8d64bbdeba'
            expected={'model.bin':('1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a',75537502),'config.json':('4065bb3bed375b176d5465be117d2d202e210434',2317),'tokenizer.json':('15d7bdf9ba25718ca2504eec6a8f02bc55af0a6a',2128466),'vocabulary.txt':('ee695b8d3e3c10d488304e04468efec4ca27554a',422309)}
            for filename,(digest,size) in expected.items():
                destination=directory/filename
                def valid(path):
                    if not path.exists() or path.stat().st_size!=size:return False
                    data=path.read_bytes()
                    actual=hashlib.sha256(data).hexdigest() if filename=='model.bin' else hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
                    return actual==digest
                if valid(destination):continue
                temporary=directory/(filename+'.part')
                with requests.get(f'https://huggingface.co/Systran/faster-whisper-tiny.en/resolve/{revision}/{filename}?download=true',stream=True,timeout=(15,45)) as response:
                    response.raise_for_status();written=0
                    with temporary.open('wb') as out:
                        for chunk in response.iter_content(256*1024):
                            written+=len(chunk)
                            if written>size:raise RuntimeError('Speech model download exceeded its expected size.')
                            out.write(chunk)
                if not valid(temporary):raise RuntimeError('Speech model checksum did not match the pinned revision.')
                temporary.replace(destination)
        _model=WhisperModel(str(directory),device='cpu',compute_type='int8',cpu_threads=min(4,os.cpu_count() or 2),num_workers=1)
    return _model

def transcribe(path):
    """Never sends audio to a third party. Whitespace/silence produces no invented text."""
    try:
        # video.transcript supplies PCM16/16 kHz mono. Read it directly: this
        # avoids a PyAV API mismatch and another lossy audio conversion.
        with wave.open(str(path),'rb') as wav:
            if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):
                raise ValueError('Speech input must be mono PCM16 WAV at 16 kHz.')
            audio=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
        with _lock:
            model=local_model()
            segments,info=model.transcribe(audio,language='en',beam_size=3,vad_filter=True,condition_on_previous_text=False,word_timestamps=False,no_speech_threshold=.6)
            text=' '.join(s.text.strip() for s in segments if s.no_speech_prob<.6 and s.avg_logprob>-1)
        return amd.redact(text.strip()),'Local Whisper tiny.en · CPU int8'
    except Exception as exc:
        raise RuntimeError('Local speech recognition is unavailable. Check the model download and enter spoken facts during seller review.') from exc

if __name__=='__main__':
    with _lock:local_model()
    print('English speech model is installed and loaded on CPU.')

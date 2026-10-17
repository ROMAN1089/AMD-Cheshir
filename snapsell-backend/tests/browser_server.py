"""Disposable API for browser acceptance tests; never use the seller database."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='snapsell-browser-'),LOCAL_ACCESS='true')
os.environ.pop('SELLER_PASSWORD',None)
import app
app.amd.configured=lambda:False
app.research.start=lambda *args,**kwargs:None
if __name__=='__main__':
    from waitress import serve
    serve(app.app,host='127.0.0.1',port=5000,threads=4)

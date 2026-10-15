from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
root=Path(__file__).resolve().parents[2]
with ZipFile(root/'private'/'ebay-notifications-upload.zip','w',ZIP_DEFLATED) as archive:
 archive.writestr('_worker.js',(root/'deploy/ebay-notifications/worker.mjs').read_text(encoding='utf-8'))
 archive.writestr('index.html','<!doctype html><title>SnapSell notification receiver</title>SnapSell notification receiver')
print('Upload archive prepared with _worker.js and index.html only; no credentials.')

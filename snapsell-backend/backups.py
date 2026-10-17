"""Consistent local recovery archives. Never include model caches or dependencies."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
import store
from contextlib import closing

def create(directory=None):
    folder=Path(directory) if directory else store.ROOT/'private'/'backups'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/('snapsell-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.zip')
    entries=[]
    if store.DB.is_file():
        with tempfile.TemporaryDirectory() as temporary:
            snapshot=Path(temporary)/'snapsell.sqlite3'
            with closing(sqlite3.connect(store.DB)) as source,closing(sqlite3.connect(snapshot)) as destination:source.backup(destination)
            with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
                def add(path,name):
                    archive.write(path,name)
                    entries.append({'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
                add(snapshot,'data/snapsell.sqlite3')
                for path in store.DATA.rglob('*'):
                    relative=path.relative_to(store.DATA)
                    if not path.is_file() or path.is_symlink() or relative.parts[0] in {'models','.backups','backups'} or path.name.startswith('snapsell.sqlite3'):continue
                    add(path,'data/'+relative.as_posix())
                private=store.ROOT/'private'
                if private.is_dir():
                    for path in private.rglob('*'):
                        relative=path.relative_to(private)
                        if path.is_file() and not path.is_symlink() and relative.parts[0]!='backups' and path.suffix not in {'.log','.zip'}:add(path,'private/'+relative.as_posix())
                for path in [store.ROOT/'.env',store.ROOT.parents[1]/'work'/'amd.env']:
                    if path.is_file():add(path,'config/'+path.name)
                archive.writestr('manifest.json',json.dumps({'format':1,'created_at':store.now(),'files':entries},indent=2))
    else:raise ValueError('There is no database to back up.')
    verify(target)
    return target

def verify(path):
    with zipfile.ZipFile(path) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!=1:raise ValueError('Unsupported backup format.')
        names=set()
        for entry in manifest['files']:
            name=entry['path'];parts=name.replace('\\','/').split('/')
            if parts[0] not in {'data','private','config'} or any(part in {'','..','.'} or ':' in part for part in parts):raise ValueError('Unsafe backup path.')
            if name in names:raise ValueError('Duplicate backup entry.')
            names.add(name)
            if hashlib.sha256(archive.read(name)).hexdigest()!=entry['sha256']:raise ValueError('Backup checksum failed: '+name)
        if 'data/snapsell.sqlite3' not in names or 'data/.session-secret' not in names:raise ValueError('Backup is missing the database or authorization encryption key.')
        if set(archive.namelist())!=names|{'manifest.json'}:raise ValueError('Unlisted backup entries.')
    return manifest

def restore(path,destination):
    manifest=verify(path);destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Restore into a NEW directory; existing files are never overwritten.')
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging=Path(temporary)/'restore';staging.mkdir()
        with zipfile.ZipFile(path) as archive:
            for entry in manifest['files']:
                target=staging/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(entry['path']))
        with closing(sqlite3.connect(staging/'data/snapsell.sqlite3')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Restored database integrity check failed.')
            for key,body in db.execute('SELECT id,body FROM jobs').fetchall():
                job=json.loads(body)
                if job.get('path'):job['path']=str(destination/'data/uploads'/Path(job['path']).name)
                db.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(job),key))
            db.commit()
        (staging/'RESTORE.txt').write_text('Recovered private data and credentials. Keep this folder private. Set DATA_DIR to this folder/data. Restore config/.env to the application root only after reviewing its settings. The amd.env file contains the AMD key. Model caches can be downloaded again.\n',encoding='utf-8')
        shutil.move(str(staging),str(destination))
    return destination

def daily():
    folder=store.ROOT/'private/backups'
    recent=max((p.stat().st_mtime for p in folder.glob('snapsell-*.zip')),default=0)
    if datetime.now(timezone.utc).timestamp()-recent>=86400:return create()

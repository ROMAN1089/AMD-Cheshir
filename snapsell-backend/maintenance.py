"""Previewable cleanup: keep every recorded product photo and active-job file."""
from pathlib import Path
import time
import store,photos

def disposable():
    protected=set();active_folders=set();jobs=store.all_rows('jobs')
    items=store.all_rows('items')
    owned_jobs={i.get('job_id') for i in items if i.get('job_id')}
    for item in items:
        for url in [*photos.gallery(item),item.get('original_capture_image','')]:
            try:protected.add(photos.path_for(url))
            except ValueError:pass
    for job in jobs:
        if job.get('status') in ['queued','processing'] or job['id'] in owned_jobs:
            active_folders.add((store.DATA/'media'/job['id']).resolve())
    result=[];media=(store.DATA/'media').resolve();uploads=(store.DATA/'uploads').resolve()
    for path in media.rglob('*'):
        resolved=path.resolve()
        if path.is_file() and not path.is_symlink() and time.time()-path.stat().st_mtime>=3600 and resolved.is_relative_to(media) and resolved not in protected and not any(resolved.is_relative_to(folder) for folder in active_folders):result.append(resolved)
    for job in jobs:
        if job.get('status') not in ['completed','failed','awaiting_key']:continue
        path=Path(job.get('path','')).resolve()
        if path.is_file() and not path.is_symlink() and path.is_relative_to(uploads):result.append(path)
    return sorted(set(result))

def status():
    files=disposable()
    return {'cleanup_files':len(files),'cleanup_bytes':sum(p.stat().st_size for p in files),'note':'Cleanup removes original uploads of finished/failed jobs and unused media. Product photos, saved facts and transaction history remain. Removed video uploads cannot be retried. Create a recovery backup first.'}

def cleanup():
    files=disposable();removed=0;size=0
    for path in files:
        size+=path.stat().st_size;path.unlink();removed+=1
    for job in store.all_rows('jobs'):
        if job.get('path') and not Path(job['path']).is_file():
            job.update(upload_removed=True);store.put('jobs',job)
    return {'removed_files':removed,'freed_bytes':size}

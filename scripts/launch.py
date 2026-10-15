"""Double-click launcher. Helpers stay local; only processes we start are stopped."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'snapsell-frontend'
PRIVATE = ROOT / 'private'
URL = 'http://127.0.0.1:3000'
PYTHON = ROOT / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
NEXT = FRONTEND / 'node_modules/next/dist/bin/next'

def node_path():
    candidates = [os.environ.get('SNAPSELL_NODE'), shutil.which('node'),
                  str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'),
                  str(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'nodejs/node.exe')]
    for value in candidates:
        if value and Path(value).is_file(): return str(Path(value).resolve())
    raise RuntimeError('Node.js is missing. Install Node.js 22+ or set SNAPSELL_NODE to node.exe.')

def check_environment():
    if not (ROOT/'.env').is_file(): raise RuntimeError('Missing .env. Copy .env.example to .env and configure it first.')
    if not PYTHON.is_file(): raise RuntimeError('Missing .venv. Follow Local setup in ReadMe.md.')
    if not NEXT.is_file(): raise RuntimeError('Frontend packages are missing. Run pnpm --dir snapsell-frontend install --frozen-lockfile.')
    # Use the venv interpreter explicitly, even when launch.py was called elsewhere.
    result = subprocess.run([str(PYTHON), '-c', 'import flask, requests, dotenv, waitress, cryptography, cv2, numpy, ddgs, bs4, faster_whisper, imageio_ffmpeg'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden())
    if result.returncode: raise RuntimeError('Backend packages are missing. Run .venv\\Scripts\\python -m pip install -r snapsell-backend/requirements.txt.')
    node = node_path()
    result = subprocess.run([node, '--version'], capture_output=True, text=True, **hidden())
    try: major = int(result.stdout.strip().lstrip('v').split('.')[0])
    except ValueError: raise RuntimeError('Could not read the Node.js version.') from None
    if result.returncode or major < 22: raise RuntimeError('Node.js 22 or newer is required.')
    return node

def hidden():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}

def alive(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1): return True
    except OSError: return False

def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
            data = json.load(response)
        return data.get('status') == 'healthy' and data.get('database') == 'SQLite'
    except (OSError, ValueError): return False

def source_digest():
    paths = []
    for folder in ['src', 'public']:
        paths.extend(p for p in (FRONTEND/folder).rglob('*') if p.is_file())
    paths.extend(FRONTEND/name for name in ['package.json', 'pnpm-lock.yaml', 'next.config.ts', 'tsconfig.json', 'postcss.config.mjs'] if (FRONTEND/name).is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(FRONTEND).as_posix().encode())
        digest.update(b'\0'); digest.update(path.read_bytes()); digest.update(b'\0')
    # Rewrites are baked into the build, not read from the environment at runtime.
    digest.update(b'BACKEND_URL=http://127.0.0.1:5000')
    return digest.hexdigest()

def prepare_build(node, env):
    fingerprint = source_digest()
    stamp = PRIVATE/'frontend-build.sha256'
    server = FRONTEND/'.next/standalone/server.js'
    if server.is_file() and (FRONTEND/'.next/BUILD_ID').is_file() and stamp.is_file() and stamp.read_text().strip() == fingerprint:
        return server
    print('Building the website. The first launch takes longer...', flush=True)
    with (PRIVATE/'build.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([node, str(NEXT), 'build'], cwd=FRONTEND, env=env, stdout=log, stderr=subprocess.STDOUT, **hidden())
    if result.returncode or not server.is_file(): raise RuntimeError('Website build failed. See private/build.log.')
    # Next standalone output intentionally leaves these assets for the deployer.
    shutil.copytree(FRONTEND/'public', server.parent/'public', dirs_exist_ok=True)
    shutil.copytree(FRONTEND/'.next/static', server.parent/'.next/static', dirs_exist_ok=True)
    stamp.write_text(fingerprint, encoding='utf-8')
    return server

def launch(command, cwd, env, name, children, logs):
    log = (PRIVATE/(name+'.log')).open('a', encoding='utf-8')
    logs.append(log)
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, **hidden())
    children.append((name, process))
    return process

def wait_ready(port, process, name, timeout=75):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if process.poll() is not None: raise RuntimeError(f'{name} exited. See private/{name}.log.')
        if healthy(port): return
        time.sleep(.5)
    raise RuntimeError(f'{name} did not become ready. See private/{name}.log.')

def stop_owned(children):
    for _, process in reversed(children):
        if process.poll() is not None: continue
        if os.name == 'nt':
            # A live Popen handle identifies our own process; never kill by port.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden())
        else: process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill()

def main():
    parser = argparse.ArgumentParser(description='Start the local SnapSell website and API.')
    parser.add_argument('--check', action='store_true', help='Check dependencies without starting servers or opening a browser.')
    parser.add_argument('--no-browser', action='store_true', help='Start without opening the default browser.')
    args = parser.parse_args()
    children, logs = [], []
    try:
        node = check_environment()
        if args.check:
            print('Ready: Python environment, backend packages, Node.js and frontend packages are available.')
            return 0
        # Avoid two launchers racing to build or bind the same ports.
        PRIVATE.mkdir(exist_ok=True)
        lock = socket.socket()
        try: lock.bind(('127.0.0.1', 54329))
        except OSError:
            lock.close()
            if healthy(5000) and healthy(3000):
                print('SnapSell is already running: '+URL)
                if not args.no_browser: webbrowser.open(URL)
                return 0
            raise RuntimeError('SnapSell is starting in another launcher window. Wait until it is ready.') from None
        with lock:
            for port in [5000, 3000]:
                if alive(port) and not healthy(port): raise RuntimeError(f'Port {port} is occupied by another service or is still starting. No process was stopped.')
            env = dict(os.environ)
            env.update(BACKEND_URL='http://127.0.0.1:5000', NEXT_TELEMETRY_DISABLED='1')
            env['PATH'] = str(Path(node).parent)+os.pathsep+env.get('PATH','')
            if not healthy(5000):
                backend_env = {**env, 'HOST':'127.0.0.1', 'PORT':'5000'}
                backend = launch([str(PYTHON), 'snapsell-backend/app.py'], ROOT, backend_env, 'backend', children, logs)
                wait_ready(5000, backend, 'backend')
            else: print('Using the backend already running on port 5000.')
            if not healthy(3000):
                server = prepare_build(node, env)
                frontend_env = {**env, 'HOSTNAME':'127.0.0.1', 'PORT':'3000'}
                frontend = launch([node, str(server)], server.parent, frontend_env, 'frontend', children, logs)
                wait_ready(3000, frontend, 'frontend')
            else: print('Using the website already running on port 3000.')
            print('\nSnapSell is ready: '+URL, flush=True)
            if not args.no_browser: webbrowser.open(URL)
            if not children: return 0
            print('Keep this window open. Press Ctrl+C here to stop the servers started by this launcher.', flush=True)
            while True:
                for name, process in children:
                    if process.poll() is not None: raise RuntimeError(f'{name} stopped. See private/{name}.log.')
                time.sleep(1)
    except KeyboardInterrupt:
        print('\nStopping SnapSell...')
        return 0
    except (RuntimeError, OSError) as error:
        print('\nCould not start SnapSell: '+str(error), file=sys.stderr)
        return 1
    finally:
        stop_owned(children)
        for log in logs: log.close()

if __name__ == '__main__':
    sys.exit(main())

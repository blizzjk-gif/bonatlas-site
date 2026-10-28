"""Stage static releases, activate with a backup, or roll back; media stays separate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
import urllib.request
from reg_transport import Transport
from site_paths import is_unmanaged_path

DOMAINS = {"dev": "dev.bonatlas.ru", "prod": "bonatlas.ru"}


def safe_path(path):
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or '..' in parsed.parts or not parsed.parts or '\\' in path:
        raise ValueError(f"Unsafe release path: {path}")
    if parsed.parts[0] in ("images", "uploads", ".well-known"):
        raise ValueError(f"Media and validation files cannot be deployed as code: {path}")
    if is_unmanaged_path(path):
        raise ValueError(f"Path is not managed by the site deployment: {path}")
    return path


def read_json(remote, path):
    return json.loads(remote.read(path))


def check_media(remote, root, metadata):
    for path, record in metadata.get("media", {}).items():
        if not path.startswith('/uploads/') or '..' in PurePosixPath(path).parts:
            raise ValueError(f"Invalid media path: {path}")
        if remote.size(root + path) != record["size"]:
            raise RuntimeError(f"Media missing on {root}: {path}. Upload media separately first.")


def stage(remote, source, environment, release):
    metadata = json.loads((source / 'release.json').read_text('utf-8'))
    if metadata['environment'] != environment or metadata['id'] != release:
        raise ValueError("Build environment/release does not match deployment")
    for name in metadata['files']:
        safe_path(name)
    root = f"/www/{DOMAINS[environment]}"
    check_media(remote, root, metadata)
    destination = f"/bonatlas-releases/{environment}/staged/{release}"
    for name, digest in metadata['files'].items():
        safe_path(name)
        local = source / name
        if hashlib.sha256(local.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Build changed after preparation: {name}")
        remote.upload(local, destination + '/' + name)
    remote.upload(source / 'release.json', destination + '/release.json')
    print(f"Staged {environment} {release}", flush=True)


def current_files(remote, root):
    if remote.size(root + '/release.json') is not None:
        return [name for name in read_json(remote, root + '/release.json')['files']
                if not is_unmanaged_path(name)] + ['release.json']
    found = []
    def walk(relative=''):
        for name, info in remote.list_files(root + '/' + relative):
            if name.startswith('.') or name in ('images', 'uploads'):
                continue
            path = relative + name
            if is_unmanaged_path(path):
                continue
            if info.get('type') == 'dir':
                walk(path + '/')
            elif info.get('type') == 'file':
                found.append(safe_path(path))
    walk()
    return found


def backup(remote, root, environment):
    files = current_files(remote, root)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = f"/bonatlas-releases/{environment}/backups/{stamp}"
    for name in files:
        safe_path(name)
        remote.copy(root + '/' + name, destination + '/' + name)
    remote.write(destination + '/snapshot.json', json.dumps({'files': files}).encode())
    print(f"Backup {stamp}", flush=True)
    return destination, files


def restore(remote, root, saved, current):
    files = [safe_path(name) for name in read_json(remote, saved + '/snapshot.json')['files']
             if not is_unmanaged_path(name)]
    for name in files:
        remote.copy(saved + '/' + safe_path(name), root + '/' + name)
    for name in set(current) - set(files):
        if is_unmanaged_path(name):
            continue
        remote.delete(root + '/' + safe_path(name))


def health(environment, release):
    url = f"https://{DOMAINS[environment]}/release.json?check={release}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                metadata = json.load(response)
            if metadata['id'] == release and metadata['environment'] == environment:
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(3)
    raise RuntimeError(f"HTTPS health check failed for {environment} {release}")


def activate(remote, environment, release, health_check=health):
    root = f"/www/{DOMAINS[environment]}"
    staged = f"/bonatlas-releases/{environment}/staged/{release}"
    metadata = read_json(remote, staged + '/release.json')
    if metadata['id'] != release or metadata['environment'] != environment:
        raise ValueError('Staged build identity mismatch')
    check_media(remote, root, metadata)
    for name, digest in metadata['files'].items():
        safe_path(name)
        if hashlib.sha256(remote.read(staged + '/' + name)).hexdigest() != digest:
            raise RuntimeError(f"Incomplete staged release: {name}")
    saved, previous = backup(remote, root, environment)
    new_files = list(metadata['files']) + ['release.json']
    try:
        for name in new_files:
            remote.copy(staged + '/' + name, root + '/' + name)
        for name in set(previous) - set(new_files):
            remote.delete(root + '/' + safe_path(name))
        health_check(environment, release)
    except Exception:
        restore(remote, root, saved, new_files)
        print('Activation failed; previous code restored. Media unchanged.', flush=True)
        raise
    print(f"Activated {environment} {release}; backup {saved}", flush=True)


def rollback(remote, environment, identifier):
    root = f"/www/{DOMAINS[environment]}"
    backups = f"/bonatlas-releases/{environment}/backups"
    choices = sorted(name for name in remote.list_dirs(backups)
                     if re.fullmatch(r'\d{8}T\d{12}Z', name))
    if not choices:
        raise RuntimeError('No backup available')
    identifier = choices[-1] if identifier == 'previous' else identifier
    if identifier not in choices:
        raise ValueError('Select an existing backup ID')
    selected = backups + '/' + identifier
    snapshot = read_json(remote, selected + '/snapshot.json')
    if remote.size(selected + '/release.json') is not None:
        check_media(remote, root, read_json(remote, selected + '/release.json'))
    saved, previous = backup(remote, root, environment)
    try:
        restore(remote, root, selected, previous)
        if 'release.json' in snapshot['files']:
            health(environment, read_json(remote, selected + '/release.json')['id'])
    except Exception:
        restore(remote, root, saved, snapshot['files'])
        raise
    print(f"Restored {environment} backup {identifier}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'deploy', 'activate', 'rollback', 'list'])
    parser.add_argument('--environment', choices=DOMAINS, required=True)
    parser.add_argument('--source', type=Path, default=Path('dist'))
    parser.add_argument('--release')
    parser.add_argument('--backup', default='previous')
    args = parser.parse_args()
    if args.action in ('stage', 'deploy', 'activate') and not re.fullmatch(r'[a-zA-Z0-9_-]{7,80}', args.release or ''):
        parser.error('A valid --release is required')
    with Transport() as remote:
        if args.action in ('stage', 'deploy'):
            stage(remote, args.source.resolve(), args.environment, args.release)
        if args.action in ('activate', 'deploy'):
            activate(remote, args.environment, args.release)
        if args.action == 'rollback':
            rollback(remote, args.environment, args.backup)
        if args.action == 'list':
            for kind in ('staged', 'backups'):
                path = f'/bonatlas-releases/{args.environment}/{kind}'
                if remote.is_dir(path):
                    print(kind + ': ' + ', '.join(remote.list_dirs(path)))


if __name__ == '__main__':
    main()

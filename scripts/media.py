"""Register local media and upload immutable, content-addressed files separately."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from reg_transport import Transport

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "media-manifest.json"
MAX_REPOSITORY_FILE = 50 * 1024 * 1024


def validate_record(original, record):
    source = PurePosixPath(original)
    if ('\\' in original or '..' in source.parts or not original.startswith(('/images/', '/uploads/'))
            or not source.name or not re.fullmatch(r'[a-f0-9]{64}', record.get('sha256', ''))):
        raise ValueError(f'Invalid media record: {original}')
    expected = f"/uploads/{record['sha256']}/{source.name}"
    repository = f"media/objects/{record['sha256']}/{source.name}"
    if record.get('path') != expected or type(record.get('size')) is not int or record['size'] <= 0:
        raise ValueError(f'Invalid media target: {original}')
    if 'repository' in record and record['repository'] != repository:
        raise ValueError(f'Invalid repository media path: {original}')


def check_file(file, record):
    if not file.is_file() or file.stat().st_size != record['size'] or hashlib.sha256(file.read_bytes()).hexdigest() != record['sha256']:
        raise RuntimeError(f'Missing or changed media: {file}')


def repository_file(record):
    file = ROOT / record['repository']
    if not file.resolve().is_relative_to((ROOT / 'media/objects').absolute()):
        raise ValueError(f'Media escapes repository storage: {file}')
    return file


def validate_entries(entries):
    for original, record in entries.items():
        validate_record(original, record)
        if 'repository' in record:
            check_file(repository_file(record), record)


def register(root, selected=None):
    root = root.resolve()
    entries = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}
    files = [root / name for name in selected] if selected else [
        file for directory in ('images/atlas', 'images/plot', 'images/brand', 'uploads')
        for file in sorted((root / directory).rglob('*')) if file.is_file() and not file.name.startswith('.')
    ]
    planned = []
    for file in files:
        if not file.resolve().is_relative_to(root) or not file.is_file():
            raise ValueError(f'Media must be a file inside {root}: {file}')
        if selected and file.stat().st_size > MAX_REPOSITORY_FILE:
            raise ValueError('Repository media must be 50 MiB or smaller; use separate upload for large files')
        data = file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        source = '/' + file.relative_to(root).as_posix()
        record = {'path': f'/uploads/{digest}/{file.name}', 'sha256': digest, 'size': len(data)}
        if selected:
            record['repository'] = f'media/objects/{digest}/{file.name}'
        elif entries.get(source, {}).get('sha256') == digest and 'repository' in entries[source]:
            record['repository'] = entries[source]['repository']
        validate_record(source, record)
        planned.append((source, record, data))
    for source, record, data in planned:
        if 'repository' in record:
            target = repository_file(record)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError(f'Immutable repository media differs: {target}')
            target.write_bytes(data)
        entries[source] = record
    MANIFEST.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f'Registered {len(planned)} files. Commit media-manifest.json and selected media/objects files.', flush=True)


def upload(remote, entries, source, environments):
    validate_entries(entries)
    for environment in environments:
        domain = {'dev': 'dev.bonatlas.ru', 'prod': 'bonatlas.ru'}[environment]
        sent = skipped = 0
        for original, record in entries.items():
            target = f'/www/{domain}' + record['path']
            size = remote.size(target)
            if size == record['size']:
                skipped += 1
                continue
            if size is not None or remote.exists(target):
                raise RuntimeError(f'Immutable media differs on server: {target}')
            local = repository_file(record) if 'repository' in record else source / original.lstrip('/')
            check_file(local, record)
            remote.upload(local, target)
            if hashlib.sha256(remote.read(target)).hexdigest() != record['sha256']:
                raise RuntimeError(f'Uploaded media checksum mismatch: {target}')
            sent += 1
            print(f'Uploaded https://{domain}' + record['path'], flush=True)
        print(f'{environment}: uploaded {sent}, unchanged {skipped}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["register", "upload", "verify"])
    parser.add_argument("--source", type=Path, default=ROOT / "public")
    parser.add_argument("--environment", choices=["dev", "prod", "both"])
    parser.add_argument('--file', action='append', help='File relative to --source; store this file in Git for automatic upload')
    args = parser.parse_args()
    if args.action == "register":
        register(args.source, args.file)
        return
    entries = json.loads(MANIFEST.read_text("utf-8"))
    validate_entries(entries)
    if args.action == 'verify':
        print('Media manifest and repository objects verified')
        return
    if not args.environment:
        parser.error("upload requires --environment dev or prod")
    with Transport() as remote:
        upload(remote, entries, args.source, ('dev', 'prod') if args.environment == 'both' else (args.environment,))


if __name__ == "__main__":
    main()

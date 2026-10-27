"""Register local media and upload immutable, content-addressed files separately."""
import argparse
import hashlib
import json
from pathlib import Path
from reg_transport import Transport

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "media-manifest.json"


def register(root):
    entries = json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}
    for directory in ("images/atlas", "images/plot", "images/brand", "uploads"):
        for file in sorted((root / directory).rglob("*")):
            if file.is_file() and not file.name.startswith("."):
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
                source = "/" + file.relative_to(root).as_posix()
                entries[source] = {"path": f"/uploads/{digest}/{file.name}",
                                   "sha256": digest, "size": file.stat().st_size}
    MANIFEST.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"Registered {len(entries)} media files; file contents remain outside Git")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["register", "upload"])
    parser.add_argument("--source", type=Path, default=ROOT / "public")
    parser.add_argument("--environment", choices=["dev", "prod"])
    args = parser.parse_args()
    if args.action == "register":
        register(args.source)
        return
    entries = json.loads(MANIFEST.read_text("utf-8"))
    if not args.environment:
        parser.error("upload requires --environment dev or prod")
    domain = 'dev.bonatlas.ru' if args.environment == 'dev' else 'bonatlas.ru'
    with Transport() as remote:
        for original, record in entries.items():
            local = args.source / original.lstrip("/")
            target = f"/www/{domain}" + record["path"]
            if remote.size(target) == record["size"]:
                continue
            if remote.exists(target):
                raise RuntimeError(f"Immutable media differs on server: {target}")
            if not local.is_file() or hashlib.sha256(local.read_bytes()).hexdigest() != record["sha256"]:
                raise RuntimeError(f"Missing or changed local media: {local}; run register first")
            remote.upload(local, target)
            print(f"Uploaded https://{domain}" + record["path"], flush=True)


if __name__ == "__main__":
    main()

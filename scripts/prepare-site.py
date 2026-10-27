"""Prepare a static release; remove binaries and rewrite media to immutable URLs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare(source, environment, release):
    if environment not in ("dev", "prod") or not re.fullmatch(r"[a-zA-Z0-9_-]{7,80}", release):
        raise ValueError("Invalid environment or release ID")
    manifest = json.loads((ROOT / "media-manifest.json").read_text("utf-8"))
    origin = 'https://dev.bonatlas.ru' if environment == 'dev' else 'https://bonatlas.ru'
    required = {}
    for file in source.rglob("*"):
        if not file.is_file() or file.suffix not in (".html", ".css", ".js", ".json", ".xml", ".yml", ".txt"):
            continue
        if any(part in ("images", "uploads") for part in file.relative_to(source).parts):
            continue
        text = file.read_text("utf-8")
        # Process full canonical/OG URLs before root-relative references.
        for original, record in sorted(manifest.items(), key=lambda item: -len(item[0])):
            if original not in text:
                continue
            required[record["path"]] = record
            for previous_origin in ("https://bonatlas.ru", "https://dev.bonatlas.ru"):
                text = text.replace(previous_origin + original, origin + record["path"])
            text = text.replace(original, origin + record["path"])
        missing = re.findall(r'''(?<=["'(=\s])/(?:images|uploads)/[^"'<>\s)]+''', text)
        if missing:
            raise ValueError(f"Unregistered media in {file}: {missing}")
        if environment == "dev" and file.suffix == ".html":
            text = text.replace('<head>', '<head><meta name="robots" content="noindex, nofollow">', 1)
        file.write_text(text, "utf-8")
    for directory in ("images", "uploads"):
        target = (source / directory).resolve()
        if target.is_relative_to(source.resolve()) and target.is_dir():
            shutil.rmtree(target)
    if environment == "dev":
        (source / "robots.txt").write_text("User-agent: *\nDisallow: /\n", "utf-8")
    files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in source.rglob("*") if p.is_file() and p.name != "release.json"}
    metadata = {"id": release, "environment": environment, "media": required, "files": files}
    (source / "release.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")
    print(f"Prepared {environment} {release}: {len(files)} files, {len(required)} external media")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "dist")
    parser.add_argument("--environment", choices=["dev", "prod"], required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    prepare(args.source, args.environment, args.release)

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
            for candidate in set((original, record['path'])):
                pattern = r'(?<![A-Za-z0-9_/:.\-])(?:https://(?:dev\.)?bonatlas\.ru)?' + re.escape(candidate)
                if re.search(pattern, text):
                    required[record["path"]] = record
                    text = re.sub(pattern, lambda _: origin + record['path'], text)
        missing = re.findall(r'''(?<=["'(=\s])/(?:images|uploads)/[^"'<>\s)]+\.[a-zA-Z0-9]{2,8}''', text)
        if missing:
            raise ValueError(f"Unregistered media in {file}: {missing}")
        if environment == "dev" and file.suffix == ".html":
            text = text.replace('<head>', '<head><meta name="robots" content="noindex, nofollow">', 1)
        file.write_text(text, "utf-8")
    # Vite's original CSS hash predates media URL rewriting. Give rewritten CSS
    # a content hash too, so a newly registered image cannot leave cached styles.
    replacements = {}
    for css in (source / '_astro').glob('*.css'):
        digest = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
        name = css.stem.rsplit('.', 1)[0] + '.' + digest + '.css'
        replacements[css.name] = name
        css.rename(css.with_name(name))
    for file in source.rglob('*'):
        if file.is_file() and file.suffix in ('.html', '.js', '.css'):
            text = file.read_text('utf-8')
            for original, rewritten in replacements.items():
                text = text.replace(original, rewritten)
            file.write_text(text, 'utf-8')
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

"""Create responsive WebP copies; originals and immutable published media are retained."""
import json
from pathlib import Path
import sys
from PIL import Image
import media

ROOT = Path(__file__).resolve().parents[1]

def main():
    manifest = json.loads((ROOT / 'media-manifest.json').read_text('utf-8'))
    originals = [name for name in manifest if name.endswith('.png') and (
        name.startswith('/images/') or name == '/uploads/blog/kak-postroit-scenu-cover.png')]
    records = {}; selected = []; before = after = 0
    for original in originals:
        file = ROOT / 'public' / original.lstrip('/')
        if not file.exists():
            continue
        with Image.open(file) as source:
            logo = '/brand/' in original
            if not logo and file.stat().st_size < 150_000:
                continue
            width, height = source.size
            widths = sorted(set(min(width, n) for n in ([160, 320, 640] if logo else [480, 960, 1600, 2400])))
            variants = []
            for size in widths:
                name = f'/uploads/responsive/{file.stem}-{size}.webp'
                target = ROOT / 'public' / name.lstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                resized = source.resize((size, round(height * size / width)), Image.Resampling.LANCZOS)
                resized.save(target, 'WEBP', quality=90 if logo else 87, method=6)
                selected.append(name.lstrip('/'))
                variants.append({'src': name, 'width': size})
            before += file.stat().st_size
            after += (ROOT / 'public' / variants[-1]['src'].lstrip('/')).stat().st_size
            records[original] = {'width': width, 'height': height, 'variants': variants}
    output = ROOT / 'src/data/image-variants.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    media.register(ROOT / 'public', selected)
    print(f'{len(records)} originals: {before:,} -> {after:,} bytes at largest responsive size')

if __name__ == '__main__':
    main()

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('site_media', SCRIPTS / 'media.py')
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class Remote:
    def __init__(self):
        self.files, self.uploads = {}, []

    def size(self, path):
        return len(self.files[path]) if path in self.files else None

    def exists(self, path):
        return path in self.files

    def upload(self, file, path):
        self.uploads.append(path)
        self.files[path] = file.read_bytes()

    def read(self, path):
        return self.files[path]

    def delete(self, path):
        self.files.pop(path, None)


class MediaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.public = self.root / 'public'
        (self.public / 'uploads/blog').mkdir(parents=True)
        self.source = self.public / 'uploads/blog/cover.png'
        self.source.write_bytes(b'cover-image')
        self.manifest = self.root / 'media-manifest.json'
        for name, value in [('ROOT', self.root), ('MANIFEST', self.manifest)]:
            p = patch.object(media, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.remote = Remote()

    def register(self):
        media.register(self.public, ['uploads/blog/cover.png'])
        return json.loads(self.manifest.read_text('utf-8'))

    def test_registration_selects_only_requested_file(self):
        (self.public / 'uploads/blog/unrelated.png').write_bytes(b'other')
        entries = self.register()
        self.assertEqual(list(entries), ['/uploads/blog/cover.png'])
        record = next(iter(entries.values()))
        self.assertEqual((self.root / record['repository']).read_bytes(), self.source.read_bytes())

    def test_both_environments_from_git_and_no_repeat_upload(self):
        entries = self.register()
        self.source.unlink()
        media.upload(self.remote, entries, self.public, ('dev', 'prod'))
        self.assertEqual(len(self.remote.uploads), 2)
        self.assertTrue(self.remote.uploads[0].startswith('/www/dev.bonatlas.ru/uploads/'))
        self.assertTrue(self.remote.uploads[1].startswith('/www/bonatlas.ru/uploads/'))
        media.upload(self.remote, entries, self.public, ('dev', 'prod'))
        self.assertEqual(len(self.remote.uploads), 2)

    def test_corrupt_git_file_fails_before_writing(self):
        entries = self.register()
        (self.root / next(iter(entries.values()))['repository']).write_bytes(b'bad')
        with self.assertRaisesRegex(RuntimeError, 'changed media'):
            media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(self.remote.uploads, [])

    def test_legacy_media_can_remain_only_on_hosting(self):
        entries = self.register()
        record = next(iter(entries.values()))
        del record['repository']
        self.source.unlink()
        target = '/www/dev.bonatlas.ru' + record['path']
        self.remote.files[target] = b'cover-image'
        media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(self.remote.uploads, [])
        self.remote.files.clear()
        with self.assertRaisesRegex(RuntimeError, 'Missing or changed'):
            media.upload(self.remote, entries, self.public, ('dev',))

    def test_wrong_remote_size_never_overwrites(self):
        entries = self.register()
        target = '/www/dev.bonatlas.ru' + next(iter(entries.values()))['path']
        self.remote.files[target] = b'bad'
        with self.assertRaisesRegex(RuntimeError, 'Immutable media differs'):
            media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(self.remote.files[target], b'bad')

    def test_paths_validated_before_remote_writes(self):
        entries = self.register()
        entries['/uploads/../outside.png'] = next(iter(entries.values())).copy()
        with self.assertRaises(ValueError):
            media.upload(self.remote, entries, self.public, ('dev',))
        entries.pop('/uploads/../outside.png')
        next(iter(entries.values()))['repository'] = '../secret'
        with self.assertRaises(ValueError):
            media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(self.remote.uploads, [])

    def test_outside_source_and_large_file_do_not_change_manifest(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(b'outside')
        with self.assertRaises(ValueError):
            media.register(self.public, [str(outside)])
        with patch.object(media, 'MAX_REPOSITORY_FILE', 2), self.assertRaises(ValueError):
            self.register()
        self.assertFalse(self.manifest.exists())

    def test_uploaded_bytes_verified(self):
        entries = self.register()
        with patch.object(self.remote, 'read', return_value=b'bad'), self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(self.remote.files, {})
        media.upload(self.remote, entries, self.public, ('dev',))
        self.assertEqual(len(self.remote.files), 1)

    def test_new_version_keeps_previous_object(self):
        old = next(iter(self.register().values()))
        self.source.write_bytes(b'revised-cover')
        new = next(iter(self.register().values()))
        self.assertNotEqual(old['path'], new['path'])
        self.assertEqual((self.root / old['repository']).read_bytes(), b'cover-image')


if __name__ == '__main__':
    unittest.main()

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('deployment', SCRIPTS / 'deploy-reg.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
prepare_spec = importlib.util.spec_from_file_location('prepare', SCRIPTS / 'prepare-site.py')
prepare_module = importlib.util.module_from_spec(prepare_spec)
prepare_spec.loader.exec_module(prepare_module)


class MemoryRemote:
    def __init__(self):
        self.files = {}

    def size(self, name):
        return len(self.files[name]) if name in self.files else None

    def read(self, name):
        return self.files[name]

    def write(self, name, content):
        self.files[name] = content

    def copy(self, source, target):
        self.files[target] = self.files[source]

    def delete(self, name):
        self.files.pop(name, None)

    def upload(self, local, name):
        self.files[name] = local.read_bytes()

    def list_files(self, directory):
        prefix = directory.rstrip('/') + '/'
        children = {}
        for name in self.files:
            if name.startswith(prefix):
                child, separator, _ = name[len(prefix):].partition('/')
                children[child] = {'type': 'dir' if separator else 'file'}
        return sorted(children.items())

    def list_dirs(self, directory):
        return [name for name, info in self.list_files(directory) if info['type'] == 'dir']


def metadata(identifier, files, environment='dev', media=None):
    return {'id': identifier, 'environment': environment, 'media': media or {},
            'files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.remote = MemoryRemote()
        self.root = '/www/dev.bonatlas.ru'
        self.old = {'index.html': b'previous', 'removed/index.html': b'previous article'}
        self.new = {'index.html': b'new', 'new/index.html': b'new article'}
        for name, value in self.old.items():
            self.remote.write(self.root + '/' + name, value)
        self.remote.write(self.root + '/release.json', json.dumps(metadata('old0000', self.old)).encode())
        self.remote.write(self.root + '/uploads/keep.png', b'media')
        staged = '/bonatlas-releases/dev/staged/new0000'
        for name, value in self.new.items():
            self.remote.write(staged + '/' + name, value)
        self.remote.write(staged + '/release.json', json.dumps(metadata('new0000', self.new)).encode())

    def test_success_removes_old_pages_but_preserves_media(self):
        deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
        self.assertEqual(self.remote.read(self.root + '/index.html'), b'new')
        self.assertIsNone(self.remote.size(self.root + '/removed/index.html'))
        self.assertEqual(self.remote.read(self.root + '/uploads/keep.png'), b'media')

    def test_failed_health_restores_previous_files_and_removes_new_pages(self):
        def failed(*_):
            raise RuntimeError('unhealthy')
        with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
            deployment.activate(self.remote, 'dev', 'new0000', failed)
        self.assertEqual(self.remote.read(self.root + '/index.html'), b'previous')
        self.assertEqual(self.remote.read(self.root + '/removed/index.html'), b'previous article')
        self.assertIsNone(self.remote.size(self.root + '/new/index.html'))
        self.assertEqual(self.remote.read(self.root + '/uploads/keep.png'), b'media')

    def test_corrupted_stage_never_changes_live_site(self):
        self.remote.write('/bonatlas-releases/dev/staged/new0000/index.html', b'truncated')
        before = dict(self.remote.files)
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
        self.assertEqual(before, self.remote.files)

    def test_missing_media_blocks_before_backup(self):
        staged = '/bonatlas-releases/dev/staged/new0000/release.json'
        value = json.loads(self.remote.read(staged))
        value['media'] = {'/uploads/missing.png': {'size': 123}}
        self.remote.write(staged, json.dumps(value).encode())
        before = dict(self.remote.files)
        with self.assertRaisesRegex(RuntimeError, 'Media missing'):
            deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
        self.assertEqual(before, self.remote.files)

    def test_cross_environment_build_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / 'release.json').write_text(json.dumps(metadata('new0000', {}, 'prod')))
            with self.assertRaisesRegex(ValueError, 'does not match'):
                deployment.stage(self.remote, source, 'dev', 'new0000')

    def test_path_traversal_and_media_mutation_rejected(self):
        for name in ('../index.html', '/index.html', 'uploads/file.jpg', 'images/map.png', '.well-known/token'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                deployment.safe_path(name)

    def editor_files(self):
        return {name: value for name, value in self.remote.files.items()
                if '/atlas/app/' in name}

    def add_editor(self, legacy_manifest=False):
        files = {'atlas/app/index.html': b'editor', 'atlas/app/assets/editor.js': b'app code'}
        for name, value in files.items():
            self.remote.write(self.root + '/' + name, value)
        if legacy_manifest:
            self.remote.write(self.root + '/release.json',
                              json.dumps(metadata('old0000', {**self.old, **files})).encode())

    def test_deploy_preserves_editor_even_if_old_manifest_owned_it(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.setUp()
                self.add_editor(legacy)
                editor = self.editor_files()
                deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
                self.assertEqual(self.editor_files(), editor)
                snapshots = [json.loads(value)['files'] for name, value in self.remote.files.items()
                             if name.endswith('/snapshot.json')]
                self.assertTrue(snapshots)
                self.assertTrue(all(not any(name.startswith('atlas/app/') for name in files)
                                    for files in snapshots))

    def test_fallback_scan_does_not_back_up_or_remove_editor(self):
        self.add_editor()
        self.remote.delete(self.root + '/release.json')
        self.remote.write(self.root + '/atlas/index.html', b'old landing')
        editor = self.editor_files()
        deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
        self.assertEqual(self.editor_files(), editor)
        self.assertIsNone(self.remote.size(self.root + '/atlas/index.html'))

    def test_failed_deploy_preserves_editor(self):
        self.add_editor(True)
        editor = self.editor_files()
        def failed(*_):
            raise RuntimeError('unhealthy')
        with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
            deployment.activate(self.remote, 'dev', 'new0000', failed)
        self.assertEqual(self.editor_files(), editor)

    def test_rollback_ignores_editor_in_legacy_snapshot(self):
        self.add_editor(True)
        identifier = '20260101T010101000000Z'
        saved = '/bonatlas-releases/dev/backups/' + identifier
        self.remote.write(saved + '/index.html', b'older site')
        self.remote.write(saved + '/atlas/app/index.html', b'outdated editor')
        self.remote.write(saved + '/snapshot.json',
                          json.dumps({'files': ['index.html', 'atlas/app/index.html']}).encode())
        editor = self.editor_files()
        deployment.rollback(self.remote, 'dev', identifier)
        self.assertEqual(self.remote.read(self.root + '/index.html'), b'older site')
        self.assertEqual(self.editor_files(), editor)

    def test_site_cannot_stage_editor_or_php_feedback(self):
        for name in ('atlas/app/index.html', 'atlas/app/assets/code.js', 'atlas/api/feedback.php'):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)
                (source / 'release.json').write_text(json.dumps(metadata('new0000', {name: b'code'})))
                before = dict(self.remote.files)
                with self.assertRaisesRegex(ValueError, 'not managed'):
                    deployment.stage(self.remote, source, 'dev', 'new0000')
                self.assertEqual(self.remote.files, before)

    def test_rejected_editor_stage_cannot_activate(self):
        staged = '/bonatlas-releases/dev/staged/new0000'
        self.remote.write(staged + '/release.json',
                          json.dumps(metadata('new0000', {'atlas/app/index.html': b'editor'})).encode())
        before = dict(self.remote.files)
        with self.assertRaisesRegex(ValueError, 'not managed'):
            deployment.activate(self.remote, 'dev', 'new0000', lambda *_: None)
        self.assertEqual(self.remote.files, before)


class MediaPreparationTests(unittest.TestCase):
    def test_editor_cannot_be_included_in_site_build(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'atlas/app').mkdir(parents=True)
            (source / 'atlas/app/index.html').write_text('editor')
            with self.assertRaisesRegex(ValueError, 'separately deployed'):
                prepare_module.prepare(source, 'dev', 'test0000')

    def test_php_feedback_is_excluded_from_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'dist'
            (source / 'atlas/api').mkdir(parents=True)
            (source / 'atlas/api/feedback.php').write_text('<?php echo "draft";')
            (source / 'atlas/index.html').write_text('<head></head>Atlas')
            (root / 'media-manifest.json').write_text('{}')
            with patch.object(prepare_module, 'ROOT', root):
                prepare_module.prepare(source, 'prod', 'test0000')
            self.assertFalse((source / 'atlas/api/feedback.php').exists())
            files = json.loads((source / 'release.json').read_text())['files']
            self.assertIn('atlas/index.html', files)
            self.assertNotIn('atlas/api/feedback.php', files)

    def test_urls_follow_environment_and_registered_media_stays_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'dist'
            source.mkdir()
            record = {'path': '/uploads/hash/image.png', 'sha256': 'hash', 'size': 1}
            (root / 'media-manifest.json').write_text(json.dumps({'/images/image.png': record}))
            (source / 'index.html').write_text('<head></head><img src="https://dev.bonatlas.ru/uploads/hash/image.png"><img src="/images/image.png">')
            with patch.object(prepare_module, 'ROOT', root):
                prepare_module.prepare(source, 'prod', 'test0000')
            html = (source / 'index.html').read_text()
            self.assertEqual(html.count('https://bonatlas.ru/uploads/hash/image.png'), 2)
            self.assertNotIn('dev.bonatlas.ru', html)
            metadata = json.loads((source / 'release.json').read_text())
            self.assertIn(record['path'], metadata['media'])

    def test_unregistered_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'dist'
            source.mkdir()
            (root / 'media-manifest.json').write_text('{}')
            (source / 'index.html').write_text('<img src="/images/missing.png">')
            with patch.object(prepare_module, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Unregistered'):
                prepare_module.prepare(source, 'dev', 'test0000')


if __name__ == '__main__':
    unittest.main()

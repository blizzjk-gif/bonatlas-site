import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('deployment', SCRIPTS / 'deploy-reg.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


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


if __name__ == '__main__':
    unittest.main()

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from PIL import Image
import requests

import sync_instagram as sync
import publish_instagram as publish


def jpeg():
    output = io.BytesIO()
    Image.new('RGB', (120, 120), 'white').save(output, 'JPEG')
    return output.getvalue()


def post(code, timestamp='2026-09-01T12:00:00+0000', kind='IMAGE'):
    return dict(id=code, media_type=kind, timestamp=timestamp,
                permalink=f'https://www.instagram.com/p/{code}/',
                media_url='https://scontent.cdninstagram.com/photo.jpg')


class InstagramTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'data/ig_images').mkdir(parents=True)
        self.previous = [{'permalink': 'https://www.instagram.com/p/old/',
                          'media_url': './data/ig_images/old.jpg'}]
        (self.root / 'data/instagram.json').write_text(json.dumps(self.previous))
        (self.root / 'data/ig_images/old.jpg').write_bytes(jpeg())

    def tearDown(self):
        self.temporary.cleanup()

    def test_wrong_account_is_rejected(self):
        api = sync.Instagram(Mock())
        api.get = Mock(return_value={'username': 'another-account', 'user_id': '123'})
        with self.assertRaises(sync.SyncError):
            api.account('secret')

    def test_flat_and_list_account_responses(self):
        api = sync.Instagram(Mock())
        for response in [{'username': sync.PROFILE, 'user_id': '123'},
                         {'data': [{'username': sync.PROFILE, 'user_id': '123'}]}]:
            api.get = Mock(return_value=response)
            self.assertEqual(api.account('secret'), '123')

    def test_all_pages_are_sorted_before_selecting_nine(self):
        api = sync.Instagram(Mock())
        old_posts = [post(f'old{i}', '2025-01-01T12:00:00+0000') for i in range(10)]
        latest = [post(f'new{i}', f'2026-09-{i + 1:02}T12:00:00+0000') for i in range(9)]
        api.get = Mock(side_effect=[{'data': old_posts, 'paging': {'next': 'ignored', 'cursors': {'after': 'cursor'}}}, {'data': latest}])
        result = api.posts('secret', '123')
        self.assertEqual([p['id'] for p in result], [f'new{i}' for i in reversed(range(9))])
        self.assertEqual(api.get.call_args.kwargs['after'], 'cursor')

    def test_empty_or_incomplete_pagination_fails(self):
        api = sync.Instagram(Mock())
        for response in [{'data': []}, {'data': [post('one')], 'paging': {'next': 'url'}}]:
            api.get = Mock(return_value=response)
            with self.assertRaises(sync.SyncError):
                api.posts('secret', '123')

    def test_video_uses_thumbnail_not_video(self):
        media = post('reel', kind='VIDEO')
        media['media_url'] = 'https://scontent.cdninstagram.com/video.mp4'
        media['thumbnail_url'] = 'https://scontent.cdninstagram.com/cover.jpg'
        self.assertEqual(sync.image_url(media), media['thumbnail_url'])
        del media['thumbnail_url']
        with self.assertRaises(sync.SyncError):
            sync.image_url(media)

    def test_carousel_can_use_first_child(self):
        media = post('album', kind='CAROUSEL_ALBUM')
        del media['media_url']
        media['children'] = {'data': [post('first')]}
        self.assertEqual(sync.image_url(media), media['children']['data'][0]['media_url'])

    def test_untrusted_media_and_permalinks_are_rejected(self):
        for url in ['http://scontent.cdninstagram.com/a.jpg', 'https://cdninstagram.com.example.com/a.jpg', 'https://127.0.0.1/a.jpg']:
            with self.assertRaises(sync.SyncError):
                sync.image_url(dict(media_type='IMAGE', media_url=url))
        for url in ['https://example.com/p/one/', 'javascript:alert(1)', 'https://instagram.com/p/../../one/']:
            with self.assertRaises(sync.SyncError):
                sync.permalink(url)

    def test_failed_final_download_preserves_entire_previous_feed(self):
        before = (self.root / 'data/instagram.json').read_bytes()
        with patch.object(sync, 'download', side_effect=[jpeg(), sync.SyncError('network failure')]):
            with self.assertRaises(sync.SyncError):
                sync.cache_feed(self.root, [post('new1'), post('new2')], Mock())
        self.assertEqual((self.root / 'data/instagram.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.root / 'data/ig_images').iterdir()), ['old.jpg'])

    def test_invalid_image_preserves_previous_feed(self):
        before = (self.root / 'data/instagram.json').read_bytes()
        with patch.object(sync, 'download', return_value=b'<html>Error</html>'):
            with self.assertRaises(sync.SyncError):
                sync.cache_feed(self.root, [post('new')], Mock())
        self.assertEqual((self.root / 'data/instagram.json').read_bytes(), before)

    def test_success_is_atomic_and_idempotent(self):
        with patch.object(sync, 'download', return_value=jpeg()) as download:
            self.assertTrue(sync.cache_feed(self.root, [post('new'), post('old')], Mock()))
            self.assertFalse(sync.cache_feed(self.root, [post('new'), post('old')], Mock()))
            self.assertEqual(download.call_count, 1)
        result = json.loads((self.root / 'data/instagram.json').read_text())
        self.assertEqual(len(result), 2)
        self.assertTrue(all((self.root / p['media_url']).is_file() for p in result))

    def test_renewal_is_encrypted_persistent_and_not_repeated(self):
        api = Mock()
        api.account.return_value = '123'
        api.refresh.return_value = {'access_token': 'rotated-secret', 'expires_in': 60 * sync.DAY}
        key = Fernet.generate_key().decode()
        env = {'INSTAGRAM_TOKEN_KEY': key, 'INSTAGRAM_ACCESS_TOKEN': 'bootstrap-secret'}
        with patch.object(sync.time, 'time', return_value=1000):
            self.assertEqual(sync.credentials(self.root, api, env)[0], 'bootstrap-secret')
        path = self.root / '.github/instagram-token.json'
        self.assertNotIn('bootstrap-secret', path.read_text())
        api.refresh.assert_not_called()
        renewal_time = 1000 + 2 * sync.DAY
        with patch.object(sync.time, 'time', return_value=renewal_time):
            self.assertEqual(sync.credentials(self.root, api, env)[0], 'rotated-secret')
            self.assertEqual(sync.credentials(self.root, api, {'INSTAGRAM_TOKEN_KEY': key})[0], 'rotated-secret')
        api.refresh.assert_called_once_with('bootstrap-secret')
        self.assertNotIn('rotated-secret', path.read_text())
        state = json.loads(path.read_text())
        self.assertEqual(Fernet(key.encode()).decrypt(state['token'].encode()).decode(), 'rotated-secret')
        self.assertLessEqual(state['refresh_at'] - renewal_time, 30 * sync.DAY)

    def test_rotated_token_survives_a_subsequent_media_failure(self):
        key = Fernet.generate_key().decode()
        env = {'INSTAGRAM_TOKEN_KEY': key, 'INSTAGRAM_ACCESS_TOKEN': 'bootstrap-secret'}
        api = Mock()
        api.account.return_value = '123'
        api.refresh.return_value = {'access_token': 'rotated-secret', 'expires_in': 60 * sync.DAY}
        with patch.object(sync.time, 'time', return_value=1000):
            sync.credentials(self.root, api, env)
        api.posts.side_effect = sync.SyncError('Media unavailable')
        before = (self.root / 'data/instagram.json').read_bytes()
        with patch.object(sync, 'Instagram', return_value=api), patch.object(sync.time, 'time', return_value=1000 + 2 * sync.DAY):
            with self.assertRaises(sync.SyncError):
                sync.sync_instagram(self.root, env)
        state = json.loads((self.root / '.github/instagram-token.json').read_text())
        self.assertEqual(Fernet(key.encode()).decrypt(state['token'].encode()).decode(), 'rotated-secret')
        self.assertEqual((self.root / 'data/instagram.json').read_bytes(), before)

    def test_wrong_encryption_key_does_not_overwrite_state(self):
        api = Mock()
        api.account.return_value = '123'
        env = {'INSTAGRAM_TOKEN_KEY': Fernet.generate_key().decode(), 'INSTAGRAM_ACCESS_TOKEN': 'secret'}
        sync.credentials(self.root, api, env)
        path = self.root / '.github/instagram-token.json'
        before = path.read_bytes()
        env['INSTAGRAM_TOKEN_KEY'] = Fernet.generate_key().decode()
        with self.assertRaises(sync.SyncError):
            sync.credentials(self.root, api, env)
        self.assertEqual(path.read_bytes(), before)

    def test_api_exceptions_do_not_expose_tokens(self):
        api = sync.Instagram(Mock())
        api.client.get.side_effect = requests.RequestException('https://graph.instagram.com?access_token=private-secret')
        with self.assertRaises(sync.SyncError) as error:
            api.get('refresh_access_token', 'private-secret')
        self.assertNotIn('private-secret', str(error.exception))

    def test_public_match_requires_images(self):
        client = Mock()
        client.get.return_value.json.return_value = self.previous
        client.head.return_value.status_code = 404
        self.assertFalse(publish.published(client, self.previous))
        client.head.return_value.status_code = 200
        client.head.return_value.headers = {'Content-Type': 'image/jpeg'}
        self.assertTrue(publish.published(client, self.previous))


if __name__ == '__main__':
    unittest.main()

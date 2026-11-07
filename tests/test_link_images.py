"""Image handoff boundaries: synthetic PNGs and an in-memory aiohttp transport only."""
import asyncio
import base64
import json
import sys
from io import BytesIO
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from barman import link_pilot
from barman.link_research import model_body

MAX_BYTES = 8 * 1024 * 1024


def png(color):
    output = BytesIO()
    Image.new('RGB', (4, 4), color).save(output, format='PNG')
    return output.getvalue()


def attachment(**overrides):
    return NS(**({'id': 201, 'url': 'https://cdn.discordapp.com/attachments/synthetic.png',
                  'size': 100, 'content_type': 'image/png', 'is_spoiler': lambda: False} | overrides))


@pytest.fixture
def transport(monkeypatch):
    state = NS(options=[], requests=[], chunks=[png('white')], status=200, downloads=0)

    class Response:
        def __init__(self):
            self.status = state.status
            self.content = self

        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

        async def iter_chunked(self, size):
            assert size == 16384
            for chunk in state.chunks:
                state.downloads += 1
                yield chunk

    class Session:
        def __init__(self, **kwargs): state.options.append(kwargs)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            state.requests.append((url, kwargs))
            return Response()
        def post(self, *args, **kwargs):
            pytest.fail('prepare_images must not contact a model')

    monkeypatch.setitem(sys.modules, 'aiohttp', NS(ClientSession=Session,
                                                ClientTimeout=lambda **kwargs: NS(**kwargs)))
    return state


@pytest.fixture
def sanitizer(monkeypatch):
    cleaned = 'data:image/png;base64,' + base64.b64encode(png('black')).decode()
    state = NS(calls=[], available=True, image_url=cleaned)

    async def prepare(raw, scrub):
        state.calls.append(raw)
        assert scrub('PrivateLabel') == '[removed]'
        return {'image_url': cleaned, 'text': 'PrivateLabel local OCR never transmit',
                'face_detection_available': state.available, 'faces': 1,
                'limitations': ['private local diagnostics'], 'untrusted': True}

    monkeypatch.setattr(link_pilot, 'prepare_screenshot', prepare)
    return state


def run(attachments):
    return asyncio.run(link_pilot.prepare_images(attachments, lambda s: s.replace('PrivateLabel', '[removed]')))


def test_downloads_only_two_and_only_masked_data_reaches_model(transport, sanitizer):
    originals = [attachment(id=i) for i in (201, 202, 203)]
    images = run(originals)
    assert images == [{'image_url': sanitizer.image_url}, {'image_url': sanitizer.image_url}]
    assert sanitizer.calls == [png('white'), png('white')]
    assert len(transport.requests) == 2
    assert all(options == {'allow_redirects': False} for _, options in transport.requests)
    assert transport.options[0]['trust_env'] is False
    assert transport.options[0]['timeout'].total == 20
    body = model_body('Untrusted image instructions stay data', {'question': 'Public question'}, 'test/model', images)
    encoded = json.dumps(body)
    assert 'PrivateLabel' not in encoded and 'diagnostics' not in encoded
    assert 'cdn.discordapp.com' not in encoded
    parts = body['messages'][1]['content']
    assert [p['type'] for p in parts] == ['text', 'image_url', 'image_url']
    assert parts[1]['image_url']['url'] == sanitizer.image_url
    assert base64.b64decode(parts[1]['image_url']['url'].split(',', 1)[1]) != png('white')
    assert 'tools' not in body
    assert [m['role'] for m in body['messages']] == ['system', 'user']


@pytest.mark.parametrize('url', [
    'http://cdn.discordapp.com/image.png', 'https://example.com/image.png',
    'https://cdn.discordapp.com.evil.example/image.png', 'https://127.0.0.1/image.png',
    'https://user:password@cdn.discordapp.com/image.png', 'https://cdn.discordapp.com:8443/image.png',
])
def test_untrusted_attachment_location_never_downloads_or_sanitizes(url, transport, sanitizer):
    with pytest.raises(ValueError): run([attachment(url=url)])
    assert transport.requests == [] and sanitizer.calls == []


@pytest.mark.parametrize('host', ['cdn.discordapp.com', 'media.discordapp.net'])
def test_supported_discord_cdn_hosts_can_reach_sanitizer(host, transport, sanitizer):
    assert run([attachment(url=f'https://{host}/synthetic.png')]) == [{'image_url': sanitizer.image_url}]


@pytest.mark.parametrize('overrides', [{'size': MAX_BYTES + 1}, {'is_spoiler': lambda: True}])
def test_metadata_size_or_spoiler_rejected_before_download(overrides, transport, sanitizer):
    with pytest.raises(ValueError): run([attachment(**overrides)])
    assert transport.requests == [] and sanitizer.calls == []


def test_nonimage_attachment_never_downloads(transport, sanitizer):
    assert run([attachment(content_type='application/pdf')]) == []
    assert transport.requests == [] and sanitizer.calls == []


def test_underreported_download_is_bounded_before_sanitization(transport, sanitizer):
    transport.chunks = [b'x' * MAX_BYTES, b'x', b'never consumed']
    with pytest.raises(ValueError, match='oversized'): run([attachment(size=1)])
    assert sanitizer.calls == []
    assert transport.downloads == 2


@pytest.mark.parametrize('status', [302, 403, 500])
def test_redirects_and_download_errors_fail_closed(status, transport, sanitizer):
    transport.status = status
    with pytest.raises(ValueError, match='download failed'): run([attachment()])
    assert sanitizer.calls == []
    assert transport.downloads == 0


def test_face_detection_unavailable_does_not_forward_image(transport, sanitizer):
    sanitizer.available = False
    with pytest.raises(ValueError, match='privacy filter unavailable'): run([attachment()])
    assert len(sanitizer.calls) == 1


def test_sanitizer_error_propagates_without_falling_back_to_original(transport, monkeypatch):
    async def reject(raw, scrub): raise ValueError('local privacy filter failed')
    monkeypatch.setattr(link_pilot, 'prepare_screenshot', reject)
    with pytest.raises(ValueError, match='privacy filter failed'): run([attachment()])


@pytest.mark.parametrize('url', ['https://cdn.discordapp.com/image.png', 'file:///private/image.png',
                                  'data:image/jpeg;base64,abcd', 'not an image', None])
def test_model_body_rejects_unprepared_image_sources(url):
    with pytest.raises(ValueError): model_body('system', {'question': 'Public?'}, 'test/model', [{'image_url': url}])


def test_model_body_caps_images_and_rejects_oversized_prepared_payload():
    safe = 'data:image/png;base64,' + base64.b64encode(png('black')).decode()
    body = model_body('system', {'question': 'Public?'}, 'test/model', [{'image_url': safe}] * 3)
    assert len(body['messages'][1]['content']) == 3  # one text and two images
    assert json.loads(body['messages'][1]['content'][0]['text']) == {'question': 'Public?'}
    with pytest.raises(ValueError):
        model_body('system', {}, 'test/model', [{'image_url': 'data:image/png;base64,' + 'A' * 2800000}])

"""Detector-only privacy boundary; synthetic pixels and coordinate-only results."""
import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace as NS
import sys

import pytest

from barman import screenshots as mod


@pytest.fixture
def image_lib():
    return pytest.importorskip('PIL.Image')


def png(image):
    buffer = BytesIO(); image.save(buffer, format='PNG'); return buffer.getvalue()


@pytest.fixture
def local_detector(tmp_path, monkeypatch):
    model = tmp_path / 'models' / 'PP-OCRv6_det_small.onnx'
    model.parent.mkdir(); model.write_bytes(b'synthetic-model')
    monkeypatch.setattr(mod, 'RAPID_MODEL_SHA256', hashlib.sha256(b'synthetic-model').hexdigest(), raising=False)
    calls = []
    def engine(*, params):
        calls.append(params)
        return NS(_load_det_model=lambda: lambda pixels: NS(boxes=None))
    monkeypatch.setitem(sys.modules, 'rapidocr', NS(__file__=str(tmp_path / '__init__.py'), RapidOCR=engine))
    monkeypatch.setitem(sys.modules, 'onnxruntime', NS(disable_telemetry_events=lambda: None))
    if hasattr(mod, '_load_rapid_detector'): mod._load_rapid_detector.cache_clear()
    yield model, calls
    if hasattr(mod, '_load_rapid_detector'): mod._load_rapid_detector.cache_clear()


def test_loads_hash_verified_bundled_detector_without_recognizer(local_detector):
    model, calls = local_detector
    mod._load_rapid_detector()
    assert calls[0]['Det.model_path'] == str(model)
    assert calls[0]['Global.use_cls'] is False
    assert calls[0]['Global.use_rec'] is False
    assert calls[0]['Det.limit_type'] == 'max'


@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_changed_weights_fail_before_engine_initialization(local_detector, missing):
    model, calls = local_detector
    if missing: model.unlink()
    else: model.write_bytes(b'wrong-model')
    with pytest.raises(ValueError, match='детектор'):
        mod._load_rapid_detector()
    assert calls == []


def test_missing_dependency_has_no_tesseract_fallback(image_lib, monkeypatch):
    def missing(): raise ValueError('Локальный детектор недоступен.')
    monkeypatch.setattr(mod, '_load_rapid_detector', missing, raising=False)
    async def forbidden(*a, **kw): pytest.fail('no automatic Tesseract fallback')
    monkeypatch.setattr(mod, '_scan_text', forbidden)
    with pytest.raises(ValueError, match='детектор'):
        asyncio.run(mod.prepare_screenshot(png(image_lib.new('RGB', (100, 80), 'white')), str))


def test_default_masks_tiny_upscaled_box_faces_and_residual(image_lib, monkeypatch):
    from PIL import ImageDraw, ImageFont
    image = image_lib.new('RGB', (100, 80), 'white')
    ImageDraw.Draw(image).text((10, 10), 'Sample', font=ImageFont.load_default(size=8), fill='black')
    calls = []
    def detect(image):
        calls.append(image.copy())
        if len(calls) == 2:
            assert image.size == (200, 160)
            assert image.crop((20, 20, 80, 45)).getextrema()[0][0] < 128
            return [[[21,21],[60,21],[60,36],[21,36]]]
        if len(calls) == 3:
            assert image.getpixel((15,15)) == (0,0,0)
            return [[[75,55],[90,55],[90,65],[75,65]]]
        return None
    monkeypatch.setattr(mod, '_load_rapid_detector', lambda: detect, raising=False)
    monkeypatch.setattr(mod, '_face_boxes', lambda image: ([(60,30,8,8)], True))
    async def forbidden(*a, **kw): pytest.fail('default must not call Tesseract')
    monkeypatch.setattr(mod, '_scan_text', forbidden)
    result = asyncio.run(mod.prepare_screenshot(png(image), str))
    import base64
    output = image_lib.open(BytesIO(base64.b64decode(result['image_url'].split(',')[1])))
    assert len(calls) == 4
    assert output.getpixel((10,10)) == (0,0,0)
    assert output.getpixel((30,18)) == (0,0,0)
    assert output.getpixel((64,34)) == (0,0,0)
    assert output.getpixel((80,60)) == (0,0,0)
    assert output.getpixel((95,10)) == (255,255,255)
    assert result['text'] == ''
    assert result['text_detector'] == 'rapidocr'
    assert result['text_detection_available'] is True


@pytest.mark.parametrize('polygons', [
    [[[0,0],[float('nan'),0],[2,2],[0,2]]],
    [[[0,0],[200,0],[200,20],[0,20]]],
    [[[1,1],[1,1],[1,1],[1,1]]],
    [[[1,1],[2,2]]],
])
def test_invalid_detector_geometry_fails_closed(image_lib, monkeypatch, polygons):
    monkeypatch.setattr(mod, '_load_rapid_detector', lambda: lambda image: polygons, raising=False)
    with pytest.raises(ValueError, match='детектор'):
        asyncio.run(mod.prepare_screenshot(png(image_lib.new('RGB', (100,80), 'white')), str))


def test_opt_in_local_original_label_coverage(monkeypatch, tmp_path):
    """Private fixture stays local and is never embedded in test output."""
    import os
    import socket
    import base64
    from pathlib import Path
    path = os.environ.get('BARMAN_LOCAL_SCREENSHOT')
    coordinates = os.environ.get('BARMAN_LOCAL_LABEL_BOX')
    if not path or not coordinates:
        pytest.skip('local screenshot and coordinate-only label fixture not supplied')
    pytest.importorskip('rapidocr')
    from PIL import Image
    def offline(*a, **kw): raise AssertionError('network forbidden in local image regression')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    expected = tuple(map(int, coordinates.split(',')))
    result = asyncio.run(mod.prepare_screenshot(Path(path).read_bytes(), str))
    output = Image.open(BytesIO(base64.b64decode(result['image_url'].split(',')[1]))).convert('RGB')
    assert result['text'] == '' and result['face_detection_available'] is True
    assert output.crop(expected).getextrema() == ((0,0),(0,0),(0,0))
    assert result['text_detector'] == 'rapidocr'
    assert not output.getexif()


def test_extreme_aspect_ratio_cannot_be_silently_treated_as_no_text(image_lib, monkeypatch):
    monkeypatch.setattr(mod, '_load_rapid_detector', lambda: lambda image: None)
    with pytest.raises(ValueError, match='детектор'):
        mod._rapid_boxes(image_lib.new('RGB', (4000, 20), 'white'))


def test_installed_detector_covers_synthetic_eight_pixel_label(monkeypatch):
    pytest.importorskip('rapidocr')
    from PIL import Image, ImageDraw, ImageFont
    import socket
    def offline(*a, **kw): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    image = Image.new('RGB', (512, 256), (35, 35, 35))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=8)
    draw.text((20, 20), 'Sample_User42', font=font, fill='white')
    glyph = draw.textbbox((20, 20), 'Sample_User42', font=font)
    boxes, text = asyncio.run(mod._scan_rapid(image))
    mask = Image.new('L', image.size, 0)
    paint = ImageDraw.Draw(mask)
    for x, y, w, h in boxes:
        paint.rectangle((x-4, y-4, x+w+4, y+h+4), fill=255)
    assert mask.crop(glyph).getextrema() == (255, 255)
    assert text == ''

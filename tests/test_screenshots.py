"""Synthetic images; only the local OCR/face detection boundaries are replaced."""
import asyncio
import base64
import importlib
from io import BytesIO
import sys
from types import SimpleNamespace as NS

import pytest


HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
TSV = (HEADER + '5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t95\tAlice\n'
       '5\t1\t1\t1\t1\t2\t50\t30\t15\t10\t-1\tсекрет\n').encode()


def legacy_screenshot(module, *args, **kwargs):
    return module.prepare_screenshot(*args, detector='tesseract', **kwargs)


@pytest.fixture
def module():
    return importlib.import_module('barman.screenshots')


@pytest.fixture
def image_lib():
    return pytest.importorskip('PIL.Image')


def image_bytes(image_lib, size=(100, 80), fmt='PNG', **save):
    buffer = BytesIO()
    image_lib.new('RGB', size, 'white').save(buffer, format=fmt, **save)
    return buffer.getvalue()


def output_image(image_lib, result):
    assert result['image_url'].startswith('data:image/png;base64,')
    return image_lib.open(BytesIO(base64.b64decode(result['image_url'].split(',', 1)[1])))


@pytest.fixture
def ocr(module, monkeypatch):
    class Process:
        returncode = 0
        killed = False
        reaped = False
        payload = None

        def __init__(self):
            self.payloads = []
            self.responses = [TSV, HEADER.encode(), HEADER.encode(), HEADER.encode()]

        async def communicate(self, payload=None):
            if self.payload is None:
                self.payload = payload
            self.payloads.append(payload)
            return self.responses.pop(0), b''

        def kill(self):
            self.killed = True

        async def wait(self):
            self.reaped = True

    process = Process()

    async def spawn(*args, **kwargs):
        assert args in (('tesseract', 'stdin', 'stdout', '-l', 'rus+eng', 'tsv'),
                        ('tesseract', 'stdin', 'stdout', '-l', 'rus+eng', '--psm', '11', 'tsv'))
        assert kwargs['stdin'] == asyncio.subprocess.PIPE
        assert kwargs['stdout'] == asyncio.subprocess.PIPE
        assert kwargs['stderr'] == asyncio.subprocess.PIPE
        return process

    async def exchange(process, payload):
        return await process.communicate(payload)

    async def discard(process):
        await process.communicate()

    monkeypatch.setattr(module, '_exchange', exchange)
    monkeypatch.setattr(module, '_discard_output', discard)
    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(module, '_face_boxes', lambda image: ([], False))
    return process


def test_masks_all_words_including_low_confidence_and_scrubs_ocr(module, image_lib, ocr):
    result = asyncio.run(legacy_screenshot(module, image_bytes(image_lib),
                                                  lambda text: text.replace('Alice', '[участник]')))
    image = output_image(image_lib, result)
    assert image.getpixel((9, 9)) == (0, 0, 0)  # padding outside Alice's box
    assert image.getpixel((55, 35)) == (0, 0, 0)  # confidence -1 still masked
    assert image.getpixel((90, 70)) == (255, 255, 255)
    assert result['text'] == '[участник] секрет'
    assert result['boxes'] == 2
    assert result['untrusted'] is True
    assert result['limitations']
    assert 'Alice' not in repr(result)


@pytest.mark.parametrize('payload', [b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'bad', b'x' * (8 * 1024 * 1024 + 1)],
                         ids=['empty', 'svg', 'invalid', 'oversized'])
def test_rejects_bad_or_oversized_input(module, payload):
    with pytest.raises(ValueError):
        asyncio.run(legacy_screenshot(module, payload, str))


def test_rejects_pixel_overflow_before_ocr(module, image_lib, ocr):
    with pytest.raises(ValueError):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib, (4001, 2000)), str))
    assert ocr.payload is None


def test_exact_pixel_limit_resizes_after_full_resolution_ocr(module, image_lib, ocr):
    result = asyncio.run(legacy_screenshot(module, image_bytes(image_lib, (4000, 2000)), str))
    assert image_lib.open(BytesIO(ocr.payload)).size == (4000, 2000)
    image = output_image(image_lib, result)
    assert image.size == (1280, 640)
    assert len(result['image_url'].encode()) <= 2 * 1024 * 1024


def test_strips_exif_before_ocr_and_output(module, image_lib, ocr):
    exif = image_lib.Exif()
    exif[315] = 'Private author'
    raw = image_bytes(image_lib, fmt='JPEG', exif=exif)
    result = asyncio.run(legacy_screenshot(module, raw, str))
    assert not image_lib.open(BytesIO(ocr.payload)).getexif()
    assert not output_image(image_lib, result).getexif()
    assert b'Private author' not in base64.b64decode(result['image_url'].split(',')[1])


def test_rejects_animation(module, image_lib, ocr):
    buffer = BytesIO()
    image_lib.new('RGB', (40, 40), 'white').save(
        buffer, format='PNG', save_all=True,
        append_images=[image_lib.new('RGB', (40, 40), 'black')])
    with pytest.raises(ValueError):
        asyncio.run(legacy_screenshot(module, buffer.getvalue(), str))
    assert ocr.payload is None


def test_timeout_kills_and_reaps_without_returning_image(module, image_lib, ocr, monkeypatch):
    async def hang(payload=None):
        if ocr.killed:
            return b'', b''
        await asyncio.Future()

    async def timeout(awaitable, timeout):
        assert timeout == 20
        awaitable.close()
        raise asyncio.TimeoutError

    ocr.communicate = hang
    monkeypatch.setattr(module.asyncio, 'wait_for', timeout)
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert ocr.killed and ocr.reaped


def test_missing_ocr_fails_closed(module, image_lib, monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError('private executable path')

    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', missing)
    with pytest.raises(ValueError, match='OCR') as exc:
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert 'private' not in str(exc.value)


def test_detected_faces_are_masked_with_padding(module, image_lib, ocr, monkeypatch):
    monkeypatch.setattr(module, '_face_boxes', lambda image: ([(70, 50, 10, 10)], True))
    result = asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert output_image(image_lib, result).getpixel((69, 49)) == (0, 0, 0)
    assert result['faces'] == 1
    assert result['faces_masked'] is True
    assert result['face_detection_available'] is True
    assert result['limitations']  # even detection is not perfect anonymity


def test_malformed_ocr_coordinates_fail_closed(module, image_lib, ocr):
    async def malformed(payload):
        return (HEADER + '5\t1\t1\t1\t1\t1\tx\t10\t20\t10\t95\tAlice\n').encode(), b''

    ocr.communicate = malformed
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))


def test_cancellation_kills_and_reaps(module, image_lib, ocr):
    async def cancelled(payload=None):
        if ocr.killed:
            return b'', b''
        raise asyncio.CancelledError

    ocr.communicate = cancelled
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert ocr.killed and ocr.reaped


def test_timeout_drains_pipes_before_reaping(module, image_lib, ocr, monkeypatch):
    drained = False

    async def communicate(payload=None):
        nonlocal drained
        if ocr.killed:
            drained = True
            return b'', b''
        await asyncio.Future()

    async def wait():
        # Real asyncio pipe transports can prevent wait() completing until
        # buffered stdout is drained, even after the child has been killed.
        assert drained
        ocr.reaped = True

    async def timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    ocr.communicate, ocr.wait = communicate, wait
    monkeypatch.setattr(module.asyncio, 'wait_for', timeout)
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert ocr.killed and ocr.reaped


def test_ocr_nonzero_exit_and_empty_output_fail_closed(module, image_lib, ocr):
    ocr.returncode = 1
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    ocr.returncode = 0

    async def empty(payload):
        return b'', b''

    ocr.communicate = empty
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))


def test_decompression_bomb_fails_closed(module, image_lib, ocr, monkeypatch):
    monkeypatch.setattr(image_lib, 'MAX_IMAGE_PIXELS', 1000)
    with pytest.raises(ValueError):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))
    assert ocr.payload is None


def test_scrub_failure_never_exposes_ocr(module, image_lib, ocr):
    def broken(text):
        raise RuntimeError(text)

    with pytest.raises(ValueError) as exc:
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), broken))
    assert 'Alice' not in str(exc.value)


def test_exact_input_byte_limit_is_accepted(module, image_lib, ocr):
    raw = image_bytes(image_lib)
    raw += b'\0' * (8 * 1024 * 1024 - len(raw))
    result = asyncio.run(legacy_screenshot(module, raw, str))
    assert result['boxes'] == 2


def test_noisy_image_output_is_bounded(module, image_lib, ocr):
    import random

    # Deterministic synthetic noise defeats RGB PNG compression.
    image = image_lib.frombytes('RGB', (1280, 1280), random.Random(7).randbytes(1280 * 1280 * 3))
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    result = asyncio.run(legacy_screenshot(module, buffer.getvalue(), str))
    assert len(result['image_url'].encode('ascii')) <= 2 * 1024 * 1024
    assert output_image(image_lib, result).convert('RGB').getpixel((15, 15)) == (0, 0, 0)


def test_second_pass_checks_masked_output_and_masks_residual_words(module, image_lib, ocr, caplog):
    ocr.responses[2] = (HEADER + '5\t1\t1\t1\t1\t1\t75\t55\t15\t10\t0\tPrivateLabel\n').encode()
    result = asyncio.run(legacy_screenshot(module, image_bytes(image_lib), lambda text: '[local only]'))
    assert len(ocr.payloads) == 4
    second = image_lib.open(BytesIO(ocr.payloads[2]))
    assert second.getpixel((15, 15)) == (0, 0, 0)
    assert second.getpixel((80, 60)) == (255, 255, 255)
    assert output_image(image_lib, result).getpixel((80, 60)) == (0, 0, 0)
    assert result['boxes'] == 3
    assert result['text_local_only'] is True
    assert result['face_detection_available'] is False
    assert result['faces_masked'] is False
    assert 'Alice' not in caplog.text and 'PrivateLabel' not in caplog.text


def test_second_pass_ocr_unavailable_fails_closed(module, image_lib, ocr, monkeypatch):
    original = module.asyncio.create_subprocess_exec
    calls = 0

    async def spawn(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise FileNotFoundError
        return await original(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(ValueError, match='OCR'):
        asyncio.run(legacy_screenshot(module, image_bytes(image_lib), str))


@pytest.mark.parametrize('missing_cascade', [False, True])
def test_local_haar_faces_rescale_to_original_pixels(module, image_lib, monkeypatch, missing_cascade):
    class Pixels:
        def reshape(self, height, width, channels):
            assert (height, width, channels) == (640, 1280, 3)
            return self

    class Detector:
        def empty(self):
            return missing_cascade

        def detectMultiScale(self, pixels, **kwargs):
            return [(100, 200, 30, 40)]

    def classifier(path):
        assert path == '/local/cascades/haarcascade_frontalface_default.xml'
        return Detector()

    monkeypatch.setitem(sys.modules, 'cv2', NS(
        data=NS(haarcascades='/local/cascades/'), CascadeClassifier=classifier,
        cvtColor=lambda pixels, mode: pixels, COLOR_RGB2GRAY=7))
    monkeypatch.setitem(sys.modules, 'numpy', NS(
        frombuffer=lambda data, dtype: Pixels(), uint8='uint8'))
    faces, available = module._face_boxes(image_lib.new('RGB', (2560, 1280), 'white'))
    if missing_cascade:
        assert faces == [] and available is False
    else:
        assert faces == [(200, 400, 60, 80)] and available is True


@pytest.fixture
def synthetic_tesseract(module, monkeypatch):
    """Exercise real pipes with a local Python child, never OCR/private pixels."""
    spawn = asyncio.create_subprocess_exec
    processes = []

    def configure(script):
        async def launch(*args, **kwargs):
            process = await spawn(sys.executable, '-c', script, **kwargs)
            processes.append(process)
            return process
        monkeypatch.setattr(module.asyncio, 'create_subprocess_exec', launch)
    return configure, processes


@pytest.mark.parametrize('language', ['rus', 'eng'])
def test_partial_language_loading_fails_closed(module, synthetic_tesseract, caplog, language):
    configure, _ = synthetic_tesseract
    configure("import sys; sys.stdin.buffer.read(); "
              f"sys.stderr.write('Failed loading language {language}\\nPRIVATE_DIAGNOSTIC'); "
              "sys.stdout.write(" + repr(HEADER) + ")")
    with pytest.raises(ValueError, match='OCR') as error:
        asyncio.run(module._ocr(b'synthetic'))
    assert 'PRIVATE' not in str(error.value) + caplog.text


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_live_pipe_overflow_kills_child_before_exit(module, synthetic_tesseract, monkeypatch, stream):
    configure, processes = synthetic_tesseract
    monkeypatch.setattr(module, 'MAX_TSV', 1024)
    configure("import sys,time; sys.stdin.buffer.read(); "
              f"sys.{stream}.buffer.write(b'x' * 100000); sys.{stream}.flush(); time.sleep(5)")

    async def run():
        with pytest.raises(ValueError, match='OCR'):
            await asyncio.wait_for(module._ocr(b'synthetic'), timeout=2)
        assert processes[0].returncode is not None
    asyncio.run(run())


def test_bounded_pipe_success_accepts_exact_limit(module, synthetic_tesseract, monkeypatch):
    configure, _ = synthetic_tesseract
    monkeypatch.setattr(module, 'MAX_TSV', 1024)
    configure("import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x' * 1024)")
    assert asyncio.run(module._ocr(b'synthetic')) == b'x' * 1024


def test_missing_cascade_api_fails_closed(module, image_lib, monkeypatch):
    monkeypatch.setitem(sys.modules, 'cv2', NS(data=NS(haarcascades='/local/cascades/')))
    monkeypatch.setitem(sys.modules, 'numpy', NS(
        frombuffer=lambda *a, **k: NS(reshape=lambda *a: None), uint8='uint8'))
    assert module._face_boxes(image_lib.new('RGB', (80, 80), 'white')) == ([], False)


def test_real_pipe_cancellation_reaps_child(module, synthetic_tesseract):
    configure, processes = synthetic_tesseract
    configure("import time; time.sleep(30)")

    async def run():
        task = asyncio.create_task(module._ocr(b'synthetic'))
        while not processes:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert processes[0].returncode is not None
    asyncio.run(run())


def test_nonfatal_ocr_diagnostic_is_not_logged(module, synthetic_tesseract, caplog):
    configure, _ = synthetic_tesseract
    configure("import sys; sys.stdin.buffer.read(); "
              "sys.stderr.write('Estimating resolution as 200\\n'); "
              "sys.stdout.write(" + repr(HEADER) + ")")
    assert asyncio.run(module._ocr(b'synthetic')) == HEADER.encode()
    assert 'Estimating resolution' not in caplog.text


def test_sparse_upscale_masks_small_label_in_original_coordinates(module, image_lib, monkeypatch):
    from PIL import ImageDraw, ImageFont
    image = image_lib.new('RGB', (100, 80), 'white')
    ImageDraw.Draw(image).text((10, 10), 'Label', font=ImageFont.load_default(size=8), fill='black')
    raw = BytesIO(); image.save(raw, format='PNG')
    calls = []

    async def recognize(data, *, psm=None):
        seen = image_lib.open(BytesIO(data)).convert('RGB')
        calls.append((psm, seen.size))
        if psm == 11 and len(calls) == 2:
            # Upsampling retains the tiny glyph signal and white surroundings.
            assert seen.crop((20, 20, 65, 45)).getextrema()[0][0] < 128
            assert seen.getpixel((160, 120)) == (255, 255, 255)
            # Outward rounding must cover original pixels 10..30, 10..18.
            return (HEADER + '5\t1\t1\t1\t1\t1\t21\t21\t39\t15\t0\tLabel\n').encode()
        return HEADER.encode()

    monkeypatch.setattr(module, '_ocr', recognize)
    monkeypatch.setattr(module, '_face_boxes', lambda image: ([], True))
    result = asyncio.run(legacy_screenshot(module, raw.getvalue(), lambda s: '[local]'))
    output = output_image(image_lib, result)
    assert calls[:2] == [(None, (100, 80)), (11, (200, 160))]
    assert output.getpixel((10, 10)) == (0, 0, 0)
    assert output.getpixel((30, 18)) == (0, 0, 0)
    assert output.getpixel((80, 60)) == (255, 255, 255)
    assert result['boxes'] == 1


def test_upscaled_ocr_working_pixels_are_bounded(module, image_lib, monkeypatch):
    sizes = []

    async def recognize(data, *, psm=None):
        sizes.append((psm, image_lib.open(BytesIO(data)).size))
        if psm == 11:
            return (HEADER + '5\t1\t1\t1\t1\t1\t1\t1\t3\t3\t0\tLabel\n').encode()
        return HEADER.encode()

    monkeypatch.setattr(module, '_ocr', recognize)
    boxes, _ = asyncio.run(module._scan_text(image_lib.new('RGB', (4000, 2000), 'white')))
    assert boxes == [(0, 0, 3, 3)]
    assert sizes[0] == (None, (4000, 2000))
    width, height = sizes[1][1]
    assert sizes[1][0] == 11 and width > 4000 and height > 2000
    assert width * height <= 16_000_000

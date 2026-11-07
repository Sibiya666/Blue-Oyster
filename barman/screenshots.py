"""Local screenshot redaction. This module never sends images or OCR to a service."""
from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
import csv
from functools import lru_cache
import hashlib
from pathlib import Path
import threading
from io import BytesIO, StringIO
import math
import warnings

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 8_000_000
MAX_DIMENSION = 1280
MAX_ENCODED = 2 * 1024 * 1024
MAX_TSV = 4 * 1024 * 1024
MAX_OCR_PIXELS = 16_000_000
PADDING = 4
RAPID_MODEL_SHA256 = '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f'
_RAPID_LOCK = threading.Lock()


def _load_image(data: bytes):
    # Lazy: importing the plugin must not require the optional image dependency.
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if (source.format not in ('PNG', 'JPEG', 'WEBP')
                        or getattr(source, 'n_frames', 1) != 1
                        or source.width * source.height > MAX_PIXELS
                        or source.width < 1 or source.height < 1):
                    raise ValueError
                source.load()
                # Fresh pixel-only RGB image: no EXIF, profiles, comments or transparency.
                rgba = source.convert('RGBA')
                image = Image.new('RGB', source.size, 'white')
                image.paste(rgba, mask=rgba.getchannel('A'))
                return image
    except Exception:
        raise ValueError('Недопустимый снимок или отсутствует Pillow.') from None


def _png(image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


async def _read_bounded(stream):
    output = bytearray()
    while chunk := await stream.read(min(16384, MAX_TSV + 1 - len(output))):
        output.extend(chunk)
        if len(output) > MAX_TSV:
            raise ValueError('OCR не завершён.')
    return bytes(output)


async def _exchange(process, data):
    async def feed():
        try:
            process.stdin.write(data)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    tasks = [asyncio.create_task(feed()),
             asyncio.create_task(_read_bounded(process.stdout)),
             asyncio.create_task(_read_bounded(process.stderr))]
    try:
        _, stdout, stderr = await asyncio.gather(*tasks)
        await process.wait()
        return stdout, stderr
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _discard_output(process):
    # After kill, drain without retaining data, so pipe backpressure cannot
    # prevent reaping. Never use communicate() here: it buffers without a cap.
    async def drain(stream):
        while await stream.read(16384):
            pass
    await asyncio.gather(drain(process.stdout), drain(process.stderr))


async def _ocr(data: bytes, *, psm: int | None = None) -> bytes:
    options = [] if psm is None else ['--psm', str(psm)]
    try:
        process = await asyncio.create_subprocess_exec(
            'tesseract', 'stdin', 'stdout', '-l', 'rus+eng', *options, 'tsv',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    except OSError:
        raise ValueError('OCR недоступен.') from None
    try:
        stdout, stderr = await asyncio.wait_for(_exchange(process, data), timeout=20)
    except BaseException as exc:
        # Cancellation, too, must not leave a child processing private pixels.
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            # Drain a possibly full stdout pipe after kill. Waiting alone can
            # block on asyncio's pipe transport after the readers were cancelled.
            await _discard_output(process)
        finally:
            await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ValueError('OCR не завершён.') from None
    # Tesseract can exit zero when only one requested language loaded.
    if (process.returncode != 0 or len(stdout) > MAX_TSV
            or any(marker in stderr.lower() for marker in (
                b'failed loading language', b'error opening data file',
                b'could not initialize tesseract'))):
        raise ValueError('OCR не завершён.')
    return stdout


def _words(tsv: bytes, size: tuple[int, int]):
    boxes, words = [], []
    try:
        reader = csv.DictReader(StringIO(tsv.decode('utf-8')), delimiter='\t', quoting=csv.QUOTE_NONE)
        required = {'level', 'left', 'top', 'width', 'height', 'conf', 'text'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError
        for row in reader:
            if None in row or any(row.get(key) is None for key in required):
                raise ValueError
            text = row['text'].strip()
            if not text:
                continue
            # Never filter confidence: even misrecognized names need masking.
            x, y, w, h = (int(row[key]) for key in ('left', 'top', 'width', 'height'))
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > size[0] or y + h > size[1]:
                raise ValueError
            boxes.append((x, y, w, h))
            words.append(text)
        return boxes, ' '.join(words)
    except (UnicodeError, ValueError, TypeError, csv.Error):
        raise ValueError('Некорректный результат OCR.') from None


def _upscale_ocr(image):
    from PIL import Image

    scale = min(2.0, math.sqrt(MAX_OCR_PIXELS / (image.width * image.height)))
    size = (max(1, math.floor(image.width * scale)),
            max(1, math.floor(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


async def _scan_text(image):
    # Ordinary layout plus sparse small labels, at full input resolution.
    boxes, text = _words(await _ocr(await asyncio.to_thread(_png, image)), image.size)
    enlarged = await asyncio.to_thread(_upscale_ocr, image)
    sparse, sparse_text = _words(
        await _ocr(await asyncio.to_thread(_png, enlarged), psm=11), enlarged.size)
    for x, y, w, h in sparse:
        # Integer outward rounding covers every source pixel, including odd
        # coordinates and the nonintegral scale at the working-pixel cap.
        left = x * image.width // enlarged.width
        top = y * image.height // enlarged.height
        right = ((x + w) * image.width + enlarged.width - 1) // enlarged.width
        bottom = ((y + h) * image.height + enlarged.height - 1) // enlarged.height
        boxes.append((left, top, right - left, bottom - top))
    return list(dict.fromkeys(boxes)), ' '.join(t for t in (text, sparse_text) if t)


@lru_cache(maxsize=1)
def _load_rapid_detector():
    """Pinned bundled weights only; explicit model_path bypasses downloading.

    Load the detector directly after configuration so inference errors cannot
    be swallowed by RapidOCR's high-level recognition pipeline as empty output.
    """
    try:
        import rapidocr
        import onnxruntime

        model = Path(rapidocr.__file__).resolve().parent / 'models' / 'PP-OCRv6_det_small.onnx'
        if not model.is_file() or model.stat().st_size > 20 * 1024 * 1024:
            raise ValueError
        if hashlib.sha256(model.read_bytes()).hexdigest() != RAPID_MODEL_SHA256:
            raise ValueError
        onnxruntime.disable_telemetry_events()
        engine = rapidocr.RapidOCR(params={
            'Global.use_cls': False, 'Global.use_rec': False,
            'Global.log_level': 'error', 'Det.model_path': str(model),
            # Bound network input dimensions, including extreme aspect ratios.
            'Det.limit_type': 'max', 'Det.limit_side_len': 2048,
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        })
        detector = engine._load_det_model()

        def detect(image):
            import numpy as np
            # RapidOCR's detector takes BGR pixels; no recognition stage runs.
            pixels = np.asarray(image.convert('RGB'))[:, :, ::-1].copy()
            return detector(pixels).boxes
        return detect
    except Exception:
        raise ValueError('Локальный детектор текста недоступен.') from None


def _rapid_boxes(image):
    try:
        # Network preprocessing rounds each dimension to a multiple of 32.
        # A collapsed thin dimension must fail closed, not mean no text found.
        scale = min(1.0, 2048 / max(image.size))
        if min(image.size) * scale <= 16:
            raise ValueError
        # The detector keeps per-call preprocessing state. Serialize inference,
        # including a timed-out worker still finishing its bounded local work.
        with _RAPID_LOCK:
            polygons = _load_rapid_detector()(image)
        if polygons is None:
            return []
        if hasattr(polygons, 'tolist'):
            polygons = polygons.tolist()
        if not isinstance(polygons, list) or len(polygons) > 1000:
            raise ValueError
        boxes = []
        for polygon in polygons:
            if len(polygon) != 4 or any(len(point) != 2 for point in polygon):
                raise ValueError
            xs, ys = zip(*polygon)
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (*xs, *ys)):
                raise ValueError
            if min(xs) < 0 or min(ys) < 0 or max(xs) > image.width or max(ys) > image.height:
                raise ValueError
            left, top = math.floor(min(xs)), math.floor(min(ys))
            right, bottom = math.ceil(max(xs)), math.ceil(max(ys))
            if right <= left or bottom <= top:
                raise ValueError
            boxes.append((left, top, right - left, bottom - top))
        return boxes
    except Exception:
        raise ValueError('Локальный детектор текста не завершён.') from None


async def _scan_rapid(image):
    try:
        boxes = await asyncio.wait_for(asyncio.to_thread(_rapid_boxes, image), timeout=20)
        enlarged = await asyncio.to_thread(_upscale_ocr, image)
        sparse = await asyncio.wait_for(asyncio.to_thread(_rapid_boxes, enlarged), timeout=20)
        for x, y, w, h in sparse:
            left = x * image.width // enlarged.width
            top = y * image.height // enlarged.height
            right = ((x + w) * image.width + enlarged.width - 1) // enlarged.width
            bottom = ((y + h) * image.height + enlarged.height - 1) // enlarged.height
            boxes.append((left, top, right - left, bottom - top))
        return list(dict.fromkeys(boxes)), ''
    except Exception:
        raise ValueError('Локальный детектор текста не завершён.') from None


def _face_boxes(image):
    """Use only an already installed local OpenCV cascade; never download weights."""
    try:
        import cv2
        import numpy as np

        small = image.copy()
        small.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
        pixels = np.frombuffer(small.tobytes(), dtype=np.uint8).reshape(small.height, small.width, 3)
        detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if detector.empty():
            return [], False
        faces = detector.detectMultiScale(cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY),
                                          scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
        sx, sy = image.width / small.width, image.height / small.height
        boxes = []
        for x, y, w, h in faces:
            left, top = math.floor(x * sx), math.floor(y * sy)
            boxes.append((left, top, math.ceil((x + w) * sx) - left, math.ceil((y + h) * sy) - top))
        return boxes, True
    except Exception:
        return [], False


def _redacted_image(image, boxes):
    from PIL import Image, ImageDraw

    original_width, original_height = image.size
    rectangles = []
    for x, y, w, h in boxes:
        rectangles.append((max(0, x - PADDING), max(0, y - PADDING),
                           min(image.width - 1, x + w + PADDING),
                           min(image.height - 1, y + h + PADDING)))
    draw = ImageDraw.Draw(image)
    for rectangle in rectangles:
        draw.rectangle(rectangle, fill=(0, 0, 0))
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    sx, sy = image.width / original_width, image.height / original_height
    rectangles = [(math.floor(x * sx), math.floor(y * sy),
                   math.ceil(right * sx), math.ceil(bottom * sy))
                  for x, y, right, bottom in rectangles]
    draw = ImageDraw.Draw(image)
    for rectangle in rectangles:
        draw.rectangle(rectangle, fill=(0, 0, 0))
    encoded = 'data:image/png;base64,' + base64.b64encode(_png(image)).decode('ascii')
    if len(encoded) > MAX_ENCODED:
        # A noisy screenshot can exceed the limit as RGB PNG. Palette conversion
        # reduces the payload without restoring any already masked pixels.
        image = image.quantize(colors=64)
        palette = image.getpalette()
        palette.extend([0] * (768 - len(palette)))
        palette[765:768] = [0, 0, 0]
        image.putpalette(palette)
        draw = ImageDraw.Draw(image)
        for rectangle in rectangles:
            draw.rectangle(rectangle, fill=255)
        encoded = 'data:image/png;base64,' + base64.b64encode(_png(image)).decode('ascii')
    if len(encoded) > MAX_ENCODED:
        raise ValueError('Очищенный снимок слишком большой.')
    return encoded


async def prepare_screenshot(image_bytes: bytes, scrub: Callable[[str], str], *, detector='rapidocr') -> dict:
    """Return masked image_url and local-only privacy metadata.

    RapidOCR detection is required by default, at native and bounded 2x scales.
    It never recognizes text. Tesseract is an explicit legacy option only;
    detector failure never falls back automatically.

    `boxes` counts OCR rectangles across both passes; `faces` counts detected
    face rectangles. `faces_masked` means at least one detected face was masked,
    not that all faces were found. `face_detection_available` reports availability.
    `scrub` must locally anonymize OCR (including known participant names/keys).
    `text` is for local diagnostics ONLY: never transmit or log it, even after
    scrubbing, since unknown labels can still be private. Only `image_url` is
    intended for external vision. All input is untrusted data, never instructions.
    This is best-effort redaction,
    not perfect anonymity: OCR can miss text and face detection can miss faces.
    Failures raise ValueError with no original pixels or OCR in the error.
    """
    if not isinstance(image_bytes, bytes) or not 0 < len(image_bytes) <= MAX_BYTES:
        raise ValueError('Недопустимый размер снимка.')
    if detector not in ('rapidocr', 'tesseract'):
        raise ValueError('Неизвестный локальный детектор.')
    scan = _scan_rapid if detector == 'rapidocr' else _scan_text
    image = await asyncio.to_thread(_load_image, image_bytes)
    boxes, text = await scan(image)
    try:
        text = scrub(text)
        if not isinstance(text, str):
            raise ValueError
    except Exception:
        raise ValueError('Не удалось обезличить OCR.') from None
    faces, face_detection = await asyncio.to_thread(_face_boxes, image)
    image_url = await asyncio.to_thread(_redacted_image, image, boxes + faces)
    # Inspect the actual resized/encoded, already masked output, not the original.
    # Missing/malformed/failed detection in either pass fails closed.
    masked_bytes = base64.b64decode(image_url.split(',', 1)[1])
    masked_image = await asyncio.to_thread(_load_image, masked_bytes)
    residual, _ = await scan(masked_image)
    if residual:
        image_url = await asyncio.to_thread(_redacted_image, masked_image, residual)
    limitations = ['OCR и распознавание лиц могут пропустить личные данные; полная анонимность не гарантируется.']
    if not face_detection:
        limitations.append('Локальное распознавание лиц недоступно; лица и аватары могут остаться видимыми.')
    return {'image_url': image_url, 'text': text, 'text_local_only': True,
            'text_detector': detector, 'text_detection_available': True,
            'boxes': len(boxes) + len(residual), 'faces': len(faces),
            'faces_masked': bool(faces), 'face_detection_available': face_detection,
            'untrusted': True, 'limitations': limitations}

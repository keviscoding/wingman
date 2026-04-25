"""On-device OCR using Apple Vision framework (macOS).

Returns recognized text blocks with bounding-box coordinates so the
transcript builder can infer speaker side (left vs right bubbles).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import PIL.Image

# Apple Vision via PyObjC — macOS-only. Guarded so the module imports
# cleanly on Linux servers where pyobjc isn't installed; the OCR code
# paths only ever run on the desktop.
try:
    import Vision  # type: ignore
    import Quartz  # type: ignore
    from Foundation import NSDictionary  # type: ignore
except Exception:  # pragma: no cover
    Vision = None  # type: ignore
    Quartz = None  # type: ignore
    NSDictionary = None  # type: ignore


@dataclass
class TextBlock:
    """A recognized block of text with its bounding box."""
    text: str
    # Bounding box in *image* coordinates (origin top-left, 0-1 normalized)
    x: float       # left edge, 0..1
    y: float       # top edge, 0..1
    width: float   # 0..1
    height: float  # 0..1
    confidence: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def is_right_aligned(self) -> bool:
        """Heuristic: if center is in the right 55 % of the image, it's 'me'."""
        return self.center_x > 0.45


def _pil_to_cgimage(img: PIL.Image.Image):
    """Convert a PIL RGB image to a CGImage via an in-memory bitmap context."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    raw = bytearray(img.tobytes())

    colorspace = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        raw, w, h, 8, w * 4, colorspace,
        Quartz.kCGImageAlphaPremultipliedLast,
    )
    return Quartz.CGBitmapContextCreateImage(ctx)


def _recognize_sync(img: PIL.Image.Image) -> list[TextBlock]:
    """Run VNRecognizeTextRequest synchronously and return TextBlocks."""
    cgimage = _pil_to_cgimage(img)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cgimage, NSDictionary.dictionary()
    )

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)

    success = handler.performRequests_error_([request], None)
    if not success[0]:
        return []

    results: list[TextBlock] = []
    for observation in request.results():
        candidate = observation.topCandidates_(1)
        if not candidate:
            continue
        text = candidate[0].string()
        conf = candidate[0].confidence()

        # Vision bbox is bottom-left origin, normalized 0-1 — flip y
        bb = observation.boundingBox()
        x = bb.origin.x
        y = 1.0 - bb.origin.y - bb.size.height
        w = bb.size.width
        h = bb.size.height

        results.append(TextBlock(
            text=text, x=x, y=y, width=w, height=h, confidence=conf,
        ))

    # Sort top-to-bottom (ascending y)
    results.sort(key=lambda b: b.y)
    return results


async def extract_text(img: PIL.Image.Image) -> list[TextBlock]:
    """Async wrapper around the synchronous Vision OCR call."""
    return await asyncio.to_thread(_recognize_sync, img)

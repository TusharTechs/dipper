"""Citizen photo → redacted image → structured pollution features → a down-weighted observation.

Privacy first: EXIF (including GPS) is removed by re-encoding, detected faces are blurred, and the image
is downscaled before anything leaves the machine. If face detection is unavailable, the photo is not
sent to the model at all.

The model only perceives. Its features enter the evidence ledger as a separate `photo_model` observer
with low sensitivity and low feature trust, and disagreements with the citizen's own answers become
prompts for the citizen. They never overwrite the citizen's answers.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageFilter, ImageOps
from pydantic import BaseModel, Field, ValidationError

from .belief import Observation
from .model import FEATURE_LABELS, FEATURES

PHOTO_ROLE = "photo_model"
DEFAULT_MODEL = os.getenv("DIPPER_VISION_MODEL", "claude-opus-5")
GEMINI_MODEL = os.getenv("DIPPER_GEMINI_MODEL", "gemini-flash-latest")
MAX_SIDE = 1568            # long-edge size that keeps detail without wasting image tokens
PRESENT_AT = 0.6           # confidence needed to count a feature as present
CONFLICT_AT = 0.75         # confidence needed to question a citizen's answer


# ---- redaction ------------------------------------------------------------------------

@dataclass
class Redacted:
    jpeg: bytes
    width: int
    height: int
    faces_blurred: int
    face_detection: bool
    exif_removed: bool = True


def redact(image_bytes: bytes) -> Redacted:
    """Re-encode without metadata, blur faces, downscale. Raises ValueError for unreadable images."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)  # keep orientation, then drop all metadata on re-encode
        img = img.convert("RGB")
    except Exception as exc:  # PIL raises several unrelated types for bad input
        raise ValueError(f"unreadable image: {exc}") from exc
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    faces, detection = _blur_faces(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)  # no exif= argument: metadata is not written
    return Redacted(jpeg=buf.getvalue(), width=img.width, height=img.height, faces_blurred=faces, face_detection=detection)


def _blur_faces(img: Image.Image) -> tuple[int, bool]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0, False
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except AttributeError:  # OpenCV builds without the objdetect Haar module
        return 0, False
    if cascade.empty():
        return 0, False
    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    for (x, y, w, h) in boxes:
        pad = int(0.25 * max(w, h))
        box = (max(0, x - pad), max(0, y - pad), min(img.width, x + w + pad), min(img.height, y + h + pad))
        img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(radius=max(12, w // 3))), box[:2])
    return len(boxes), True


# ---- structured extraction ------------------------------------------------------------------

class FeatureCall(BaseModel):
    present: bool
    confidence: float = Field(ge=0, le=1)


class PhotoFeatures(BaseModel):
    shows_stream_or_outfall: bool
    image_usable: bool
    grey: FeatureCall
    sewage_fungus: FeatureCall
    foam: FeatureCall
    brown_turbid: FeatureCall
    green: FeatureCall
    pipe_flowing: FeatureCall
    dead_fish: FeatureCall
    note: str = Field(description="One short sentence about the water only. Never describe people.")

    def calls(self) -> dict[str, FeatureCall]:
        return {f: getattr(self, f) for f in FEATURES if hasattr(self, f)}


SYSTEM = (
    "You read a single photo taken by a citizen scientist beside an urban stream, to support a human-led "
    "pollution investigation. Report only what is visible in the water, the stream bed, the banks and any pipe "
    "or outfall. Smell cannot be judged from a photo, so it is not asked. Give each visual indicator a calibrated "
    "confidence between 0 and 1; use low confidence when lighting, distance or blur make a call uncertain. "
    "Do not identify or describe people, vehicles or property. You are one weak observer among several; a person "
    "makes every decision, so do not speculate about causes, pathogens or health effects."
)

INDICATORS = "\n".join(f"- {f}: {FEATURE_LABELS[f]}" for f in FEATURES if f in PhotoFeatures.model_fields)


def _schema() -> dict[str, Any]:
    call = {"type": "object", "additionalProperties": False, "required": ["present", "confidence"],
            "properties": {"present": {"type": "boolean"}, "confidence": {"type": "number"}}}
    props: dict[str, Any] = {"shows_stream_or_outfall": {"type": "boolean"}, "image_usable": {"type": "boolean"},
                             "note": {"type": "string"}}
    for f in PhotoFeatures.model_fields:
        if f in FEATURES:
            props[f] = call
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


class PhotoModelUnavailable(RuntimeError):
    """No credentials, a refusal, or an unusable response. The report still counts without the photo."""


def vision_provider() -> str:
    """'anthropic' or 'gemini'. DIPPER_VISION_PROVIDER wins; otherwise whichever key is configured, Claude first."""
    explicit = os.getenv("DIPPER_VISION_PROVIDER", "").strip().lower()
    if explicit in ("anthropic", "gemini"):
        return explicit
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY"):
        return "gemini"
    return "anthropic"


def extract(jpeg: bytes) -> PhotoFeatures:
    """Extract features with the configured provider. The image must already be redacted."""
    return extract_features_gemini(jpeg) if vision_provider() == "gemini" else extract_features(jpeg)


def _parse(text: str | None) -> PhotoFeatures:
    if not text:
        raise PhotoModelUnavailable("photo model returned no result")
    try:
        return PhotoFeatures.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PhotoModelUnavailable("photo model result did not match the schema") from exc


def extract_features_gemini(jpeg: bytes, client: Any | None = None, model: str = GEMINI_MODEL) -> PhotoFeatures:
    """Same contract as extract_features, using Google Gemini (google-genai SDK) with a JSON-schema response."""
    from google import genai
    from google.genai import errors, types

    if client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY")
        if not key:
            raise PhotoModelUnavailable("no photo model credentials configured (set GEMINI_API_KEY or LLM_API_KEY)")
        client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                      f"Rate these visual indicators:\n{INDICATORS}"],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM, response_mime_type="application/json", response_json_schema=_schema(),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)),  # no tools used
        )
    except errors.ClientError as exc:
        raise PhotoModelUnavailable(f"photo model rejected the request ({exc.code})") from exc
    except errors.ServerError as exc:
        raise PhotoModelUnavailable(f"photo model error {exc.code}") from exc
    except errors.APIError as exc:
        raise PhotoModelUnavailable("photo model error") from exc
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        raise PhotoModelUnavailable("the photo model declined this image")
    return _parse(getattr(response, "text", None))


def extract_features(jpeg: bytes, client: Any | None = None, model: str = DEFAULT_MODEL) -> PhotoFeatures:
    """Ask Claude for structured visual indicators. `client` is an anthropic.Anthropic (injectable for tests)."""
    import anthropic

    if client is None:
        try:
            client = anthropic.Anthropic()
        except anthropic.AnthropicError as exc:  # no credentials configured
            raise PhotoModelUnavailable(f"no photo model credentials configured: {exc}") from exc
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=2048,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(jpeg).decode()}},
                {"type": "text", "text": f"Rate these visual indicators:\n{INDICATORS}"},
            ]}],
        )
    except anthropic.AuthenticationError as exc:
        raise PhotoModelUnavailable("photo model credentials were rejected") from exc
    except anthropic.RateLimitError as exc:
        raise PhotoModelUnavailable("photo model is rate limited; try again shortly") from exc
    except anthropic.APIStatusError as exc:
        raise PhotoModelUnavailable(f"photo model error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise PhotoModelUnavailable("photo model unreachable") from exc
    except TypeError as exc:  # the SDK reports missing credentials this way, before any network call
        if "authentication method" not in str(exc):
            raise
        raise PhotoModelUnavailable("no photo model credentials configured (set ANTHROPIC_API_KEY)") from exc
    if response.stop_reason == "refusal":
        raise PhotoModelUnavailable("the photo model declined this image")
    return _parse(next((b.text for b in response.content if b.type == "text"), None))


# ---- fusion -------------------------------------------------------------------------------

@dataclass
class Conflict:
    feature: str
    citizen_said: bool
    photo_confidence: float
    prompt: str


@dataclass
class PhotoResult:
    features: PhotoFeatures
    observation: Observation | None
    conflicts: list[Conflict] = field(default_factory=list)


def to_observation(pf: PhotoFeatures, node_id: str, observed_at=None, tier: str = "observed") -> Observation | None:
    """A photo_model sighting. None when the photo is unusable or does not show the stream."""
    if not (pf.image_usable and pf.shows_stream_or_outfall):
        return None
    feats = tuple((f, c.present and c.confidence >= PRESENT_AT) for f, c in pf.calls().items()
                  if c.confidence >= PRESENT_AT or not c.present)
    positive = any(present for _, present in feats)
    return Observation("report" if positive else "instream_look", positive, node_id=node_id, role=PHOTO_ROLE,
                       features=feats if positive else (), observed_at=observed_at, tier=tier)


def conflicts(citizen: dict[str, bool], pf: PhotoFeatures) -> list[Conflict]:
    out = []
    for f, c in pf.calls().items():
        if f not in citizen:
            continue
        said = citizen[f]
        if c.confidence >= CONFLICT_AT and c.present != said:
            what = FEATURE_LABELS[f]
            prompt = (f"Your photo looks like it shows {what}. Keep your answer or change it?" if c.present
                      else f"We can't see {what} in your photo. Keep your answer or change it?")
            out.append(Conflict(f, said, round(c.confidence, 2), prompt))
    return out

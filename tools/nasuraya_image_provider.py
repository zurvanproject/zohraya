"""Optional real-image adapter for Nasuraya gallery, disabled unless --execute.

Uses the documented OpenAI Images API with a single image and a fixed, safe
character brief. All generated content stays local. Never logs or stores a key.
This is not the Tadash runtime and does not make autonomous server requests.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nasuraya_visual_gallery import DEFAULT_LETTER, MAX_IMAGE_BYTES, build

API_ENDPOINT = "https://api.openai.com/v1/images/generations"
SUPPORTED_MODELS = ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
SCENES = {
    "observatory": "an old open-air stargazing observatory above the Zagros mountain range at twilight",
    "courtyard": "a stone courtyard with grapevines and pomegranate trees after the rain",
    "library": "a small sunlit Kurdish mountain library full of books and carved oak furniture",
}
MAX_RESPONSE_BYTES = 24 * 1024 * 1024


class ImageProviderError(RuntimeError):
    """A sanitized provider or validation failure, without tokens or responses."""


def make_prompt(scene: str) -> str:
    if scene not in SCENES:
        raise ValueError("invalid scene")
    return (
        "Cinematic three-quarter portrait of an ADULT fictional fantasy character "
        "called Nasuraya in " + SCENES[scene] + ". She has long copper curly hair, "
        "expressive amber eyes, a small dark diamond mark high on the forehead, "
        "two curved crimson horns visibly and naturally attached to the head, "
        "pointed ears, a warm kind expression and a strong feminine athletic form. "
        "She wears an opaque embroidered midnight-blue and terracotta tunic "
        "and a fully covering traditional wrap. Single copper furry tail. "
        "She holds an OPEN large, completely BLANK cream paper in front of her "
        "with both hands; the paper lies in the lower foreground, flat, well-lit "
        "and facing the camera, with NO handwriting on it. "
        "Beautiful tactility, coherent anatomy, correct hands and fingers. "
        "No words, signs, logos, watermarks, nudity, or sexual content. "
        "A single character only, natural cinematic composition."
    )


def plan(scene: str = "observatory", model: str = SUPPORTED_MODELS[0],
         quality: str = "low") -> dict:
    if model not in SUPPORTED_MODELS:
        raise ValueError("unsupported image model")
    if quality not in {"low", "medium", "high"}:
        raise ValueError("unsupported image quality")
    prompt = make_prompt(scene)
    return {
        "model": model,
        "prompt": prompt,
        "size": "1024x1536",
        "quality": quality,
        "output_format": "png",
        "n": 1,
    }


def inspect_png(data: bytes) -> tuple[int, int]:
    if not isinstance(data, bytes) or len(data) < 24 or len(data) > MAX_IMAGE_BYTES:
        raise ImageProviderError("invalid image size")
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ImageProviderError("provider response is not a valid PNG header")
    w, h = struct.unpack(">II", data[16:24])
    if not (256 <= w <= 4096 and 256 <= h <= 4096):
        raise ImageProviderError("provider image dimensions out of bounds")
    return (w, h)


def request_image(request_body: dict, api_key: str, transport=urlopen) -> bytes:
    """One synchronous API call. Transport injection supports fully offline tests."""
    if not api_key or not api_key.strip():
        raise ImageProviderError("OPENAI_API_KEY is required for --execute")
    payload = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    request = Request(
        API_ENDPOINT,
        data=payload,
        method="POST",
        headers={"Authorization": "Bearer " + api_key.strip(),
                 "Content-Type": "application/json"},
    )
    try:
        with transport(request, timeout=180) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as err:
        # The HTTP error body can contain private prompts. Never echo it.
        raise ImageProviderError("image API returned HTTP " + str(err.code)) from None
    except URLError:
        raise ImageProviderError("image API connection failed") from None
    except TimeoutError:
        raise ImageProviderError("image API timed out") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ImageProviderError("image API response is too large")
    try:
        response_json = json.loads(raw.decode("utf-8"))
        data_list = response_json["data"]
        if not isinstance(data_list, list) or len(data_list) != 1:
            raise ValueError("expected exactly one image")
        b64 = data_list[0]["b64_json"]
        if not isinstance(b64, str):
            raise ValueError("image payload missing")
        result = base64.b64decode(b64, validate=True)
    except (ValueError, KeyError, TypeError, IndexError, UnicodeError, binascii.Error):
        raise ImageProviderError("image API supplied invalid data") from None
    inspect_png(result)
    return result


def execute(output: Path, scene: str, model: str, quality: str,
            api_key: str, *, transport=urlopen) -> dict:
    """Exactly one opt-in call; neither uploads nor publishes the result."""
    request_body = plan(scene, model, quality)
    data = request_image(request_body, api_key, transport=transport)
    # Only create final output after API response passes local validation.
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output, prefix="nasuraya-", suffix=".png",
                                     delete=False) as tmp:
        tmp.write(data)
        candidate = Path(tmp.name)
    try:
        width, height = inspect_png(data)
        receipt = {
            "version": 1,
            "provider": "OpenAI Images API",
            "model": model,
            "scene": scene,
            "quality": quality,
            "request_sha256": sha256(json.dumps(request_body, ensure_ascii=False,
                                                sort_keys=True).encode("utf-8")).hexdigest(),
            "image_sha256": sha256(data).hexdigest(),
            "image_width": width,
            "image_height": height,
            "images_requested": 1,
            "images_received": 1,
            "api_request_completed": True,
            "image_model_invoked": True,
            "published": False,
            "uploaded": False,
            "server_executed": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        # Do not expose an image as "approved": a person still needs to review it.
        gallery = build(output / "gallery", DEFAULT_LETTER, candidate, source_receipt=receipt)
        receipt["gallery_manifest_sha256"] = sha256(
            (output / "gallery" / "manifest.json").read_bytes()).hexdigest()
        receipt["gallery_method"] = gallery["method"]
        # Both receipts now identify the true API model and the unreviewed raster.
        (output / "api-generation-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        candidate.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=SCENES, default="observatory")
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=SUPPORTED_MODELS[0])
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--out", type=Path, default=Path("nasuraya-api-preview"))
    parser.add_argument("--execute", action="store_true",
                        help="Opt in to ONE potentially billable API request")
    args = parser.parse_args()
    if not args.execute:
        p = plan(args.scene, args.model, args.quality)
        print(json.dumps({"mode": "DRY_RUN_NO_API_NO_CHARGE", "request": p},
                         ensure_ascii=False, indent=2))
        return
    # Key is intentionally accessed only after explicit --execute.
    result = execute(args.out, args.scene, args.model, args.quality,
                     os.environ.get("OPENAI_API_KEY", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Nasuraya visual continuity v0.1: offline, honest and reviewable gallery.

No network, no model calls, no direct access to the Tadash runtime, and no publishing.
A user-approved raster image can be supplied; otherwise a deliberately simple
original vector placeholder is generated. Persian letter text remains selectable.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import shutil

DEFAULT_LETTER = (
    "سهند جان،\n"
    "امروز یک تصویر را با یک ادعا اشتباه نمی‌گیرم.\n"
    "چهره را می‌توان کشید؛ حضور را باید آزمود.\n"
    "نامه را باز می‌گذارم تا خودت بخوانی.\n"
    "قدم بعدی: یادگیری از خطا، نه پنهان‌کردن آن.\n"
    "ناسو"
)
MAX_IMAGE_BYTES = 16 * 1024 * 1024
ALLOWED_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


def validated_letter(value: str) -> list[str]:
    """Accept only small, printable, explicit letter text."""
    if not isinstance(value, str) or not value.strip() or len(value) > 700:
        raise ValueError("letter must contain 1..700 characters")
    lines = value.splitlines()
    if not 1 <= len(lines) <= 8 or any(len(line) > 61 for line in lines):
        raise ValueError("letter must have 1..8 lines of at most 61 characters")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ValueError("letter has control characters")
    return lines


def portrait_svg(letter: str) -> str:
    """Deterministic vector illustration; NOT AI-generated or photorealistic."""
    lines = validated_letter(letter)
    # A separate HTML transcript is the legibility source of truth.
    # SVG renderers vary in Persian shaping; HTML overlays provide text instead.
    letter_svg = ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 1240"
role="img" aria-label="Original vector portrait of Nasuraya holding an open Persian letter">
<defs>
  <linearGradient id="sky" x2="0" y2="1">
    <stop stop-color="#254259"/><stop offset="1" stop-color="#a9b8ac"/>
  </linearGradient>
  <linearGradient id="coat" x2="0" y2="1">
    <stop stop-color="#0b5862"/><stop offset="1" stop-color="#14343d"/>
  </linearGradient>
  <filter id="shadow"><feDropShadow dx="0" dy="9" stdDeviation="18" flood-opacity=".22"/></filter>
</defs>
<rect width="960" height="1240" fill="url(#sky)"/>
<path d="M0 510 L175 342 328 455 513 305 724 459 960 329 V770 H0Z" fill="#435d61" opacity=".82"/>
<path d="M0 620 L200 492 432 610 605 455 960 616 V890 H0Z" fill="#2d4c50" opacity=".8"/>
<path d="M0 760 Q430 665 960 777 V1240 H0Z" fill="#bda98c"/>
<path d="M0 845 H960" stroke="#9e886d" stroke-width="9"/>
<ellipse cx="330" cy="573" rx="225" ry="190" fill="#203e46" opacity=".3"/>
<!-- The adult fictional horned character, intentionally stylized. -->
<path d="M126 780 Q153 579 297 580 Q472 566 505 792 L492 1230 H120Z" fill="url(#coat)"/>
<path d="M275 582 L326 786 365 580" fill="none" stroke="#ae6255" stroke-width="18"/>
<path d="M129 790 Q160 710 190 682 M462 795 Q445 707 413 677" fill="none" stroke="#a66a4c" stroke-width="7"/>
<path d="M177 380 Q104 184 213 118 Q143 211 250 231Z" fill="#963b46" stroke="#61262b" stroke-width="13"/>
<path d="M380 350 Q500 173 409 105 Q468 223 335 232Z" fill="#963b46" stroke="#61262b" stroke-width="13"/>
<path d="M170 420 Q116 245 251 215 Q402 170 462 328 Q498 490 393 598 L177 596Z"
fill="#b85c37" stroke="#7a3528" stroke-width="12"/>
<path d="M152 350 Q102 383 136 449 Q107 489 148 525
M440 290 Q508 335 473 385 Q521 446 464 501" fill="none" stroke="#e18a4a" stroke-width="39" stroke-linecap="round"/>
<path d="M144 403 Q195 365 185 316 Q222 277 269 302 Q351 265 393 324 L406 502
Q387 604 296 631 Q192 604 173 520Z" fill="#e2ab83" stroke="#ae704d" stroke-width="9"/>
<path d="M165 448 Q115 410 132 353 L191 408 M400 413 L450 344 Q473 412 422 458" fill="#b8815c"/>
<path d="M202 423 Q239 402 264 426 M328 425 Q361 404 394 421" fill="none" stroke="#643e36" stroke-width="9" stroke-linecap="round"/>
<ellipse cx="237" cy="436" rx="13" ry="17" fill="#a46b24"/>
<ellipse cx="356" cy="436" rx="13" ry="17" fill="#a46b24"/>
<circle cx="240" cy="431" r="4" fill="#fff8d1"/><circle cx="359" cy="431" r="4" fill="#fff8d1"/>
<path d="M299 440 L285 496 Q297 508 313 498" fill="none" stroke="#aa735c" stroke-width="5"/>
<path d="M260 536 Q297 564 340 534" fill="none" stroke="#8d4a46" stroke-width="6" stroke-linecap="round"/>
<path d="M298 344 l-15 21 15 21 15-21Z" fill="#5a2f37"/>
<path d="M174 340 Q143 286 194 258 Q214 230 241 248 Q281 220 317 248 Q387 224 421 297"
fill="none" stroke="#dc7842" stroke-width="35" stroke-linecap="round"/>
<path d="M155 335 Q136 467 177 582 M434 333 Q474 469 413 584" fill="none" stroke="#cc6639" stroke-width="27" stroke-linecap="round"/>
<!-- Unfolded physical paper, foreground and hands. -->
<rect x="88" y="635" width="792" height="553" rx="13" fill="#fcf3df" stroke="#d3bea0" stroke-width="7" filter="url(#shadow)"/>
<path d="M92 906 H877" stroke="#d5c9b4" stroke-width="3" stroke-dasharray="10 8"/>
<path d="M144 693 Q125 660 104 701 L87 772 Q106 793 139 761Z" fill="#db9b78" stroke="#9c664d" stroke-width="4"/>
<path d="M816 698 Q841 660 869 700 L884 769 Q859 792 825 767Z" fill="#db9b78" stroke="#9c664d" stroke-width="4"/>
{letter_svg}
</svg>'''


def check_raster(path: Path) -> str:
    """Only explicitly supplied, small PNG/JPEG/WebP. SVG inputs are disallowed."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("image must be a nonempty local file")
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 16 MiB")
    ext = path.suffix.lower()
    fmt = ALLOWED_FORMATS.get(ext)
    if fmt is None:
        raise ValueError("only PNG, JPEG and WebP are supported")
    with path.open("rb") as stream:
        head = stream.read(16)
    signatures = {
        "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": head.startswith(b"\xff\xd8\xff"),
        "webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
    }
    if not signatures[fmt]:
        raise ValueError("image extension and format signature disagree")
    return ext


def build(output: Path, letter: str = DEFAULT_LETTER, image: Path | None = None) -> dict:
    """Build an offline gallery; it does not upload or call external services."""
    validated_letter(letter)
    if image is not None:
        ext = check_raster(image)
    else:
        ext = ".svg"
    output.mkdir(parents=True, exist_ok=True)
    art_name = "nasuraya" + ext
    art_path = output / art_name
    if image is None:
        art_path.write_text(portrait_svg(letter), encoding="utf-8")
        mode = "original-vector-fallback"
    else:
        if image.resolve() == art_path.resolve():
            raise ValueError("source image must not be output image")
        shutil.copyfile(image, art_path)
        mode = "approved-raster-input"
    text_html = "\n".join(
        f'<p class="line">{escape(line) if line else "&nbsp;"}</p>'
        for line in letter.splitlines()
    )
    overlay_html = (f'<div class="on-paper" aria-hidden="true">{text_html}</div>'
                    if image is None else "")
    page = f'''<!doctype html>
<html lang="fa" dir="rtl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline';">
<title>ناسورایا | نامهٔ باز</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#192a32;color:#f5ecd7;font-family:Tahoma,Arial,sans-serif}}
main{{width:min(960px,96vw);margin:auto;padding:24px 0 60px}}
h1{{font-size:clamp(26px,5vw,41px)}}figure{{position:relative;margin:0 auto;width:min(100%,680px)}}img{{display:block;width:100%;height:auto;object-fit:contain;background:#415561;border-radius:18px}}
.on-paper{{position:absolute;top:59%;right:15%;width:70%;height:30%;overflow:hidden;color:#2b272b;direction:rtl;text-align:right;font-family:Tahoma,Arial,sans-serif;font-size:clamp(10px,2vw,21px);line-height:1.55}}
.on-paper .line{{margin:0 0 8px;white-space:normal}}
article{{background:#f7eedb;color:#292624;margin-top:18px;border-radius:18px;padding:24px;line-height:1.9;font-size:clamp(19px,3.5vw,28px)}}
.line{{margin:0 0 8px}}small{{display:block;color:#c8cdd0;margin-top:20px;line-height:1.8}}
</style></head>
<body><main><h1>ناسورایا | نامهٔ باز</h1>
<figure><img src="{escape(art_name, quote=True)}" alt="تصویر داستانی ناسورایا با نامهٔ باز">{overlay_html}</figure>
<article aria-label="متن خوانای نامه">{text_html}</article>
<small>نمایش آزمایشی و آفلاین. تصویر برداری ساده یا فایل تصویریِ تأییدشده است. ساخت تصویر با مدل هوش مصنوعی و انتشار اینترنتی در این برنامه انجام نمی‌شود.</small>
</main></body></html>'''
    (output / "index.html").write_text(page, encoding="utf-8")
    digest = lambda path: sha256(path.read_bytes()).hexdigest()
    manifest = {
        "version": 1,
        "portrait": art_name,
        "portrait_sha256": digest(art_path),
        "index_sha256": digest(output / "index.html"),
        "method": mode,
        "image_model_invoked": False,
        "server_executed": False,
        "uploaded": False,
        "published": False,
        "quality_checks": {"visual_anatomy_reviewed": False, "letter_readable_html": True},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Offline destination folder")
    parser.add_argument("--letter-file", type=Path, help="UTF-8 letter file")
    parser.add_argument("--image", type=Path, help="User-approved local PNG/JPG/WebP (optional)")
    args = parser.parse_args()
    letter = args.letter_file.read_text(encoding="utf-8") if args.letter_file else DEFAULT_LETTER
    result = build(args.out, letter, args.image)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

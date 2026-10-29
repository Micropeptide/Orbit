"""Meta Model API: Muse Image and SAM 3.1, called directly.

The chat models (Muse Wonder, Muse Spark) go through the harness like any other provider
(bin/harness.py, "meta"). The two that are not chat models are here:

  Muse Image   POST /v1/images/generations and /v1/images/edits  -> an image file
  SAM 3.1      POST /v1/responses (streamed)                     -> boxes and masks

The key is the same one the chat models use: MODEL_API_KEY in Orbit's secrets (Settings ->
Models & keys -> Meta Model API), or in the environment. Stdlib only; the SAM masks are
decoded by Meta's own `meta-sam-parser` when it is installed, and the boxes work without it.
"""
import base64, json, mimetypes, os, re, time, urllib.error, urllib.request

BASE = "https://api.meta.ai/v1"
KEY_NAME = "MODEL_API_KEY"
KEY_ALIASES = ("MODEL_API_KEY", "META_API_KEY")        # Meta's own CLI reads META_API_KEY
IMAGE_MODEL = "muse-image-1.0"
SAM_MODEL = "sam-3.1"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif"}


class MetaError(RuntimeError):
    """Something to tell the model or the person as it is."""


def api_key(secrets=None):
    for name in KEY_ALIASES:
        v = ((secrets or {}).get(name) or os.environ.get(name) or "").strip()
        if v: return v
    return ""


def base_url(override=None):
    return (override or os.environ.get("META_API_BASE") or BASE).rstrip("/")


def _headers(key, accept="application/json"):
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": accept,
            "User-Agent": "orbit"}


def _error_text(e):
    """The message Meta put in an error body, else the status line."""
    try:
        raw = e.read().decode("utf-8", "replace")
        d = json.loads(raw)
        err = d.get("error") if isinstance(d, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or raw
    except Exception:
        msg = ""
    return f"Meta Model API said {e.code}: {str(msg or e.reason)[:600]}"


def _post(path, payload, key, timeout=300, accept="application/json", base=None):
    req = urllib.request.Request(base_url(base) + path, data=json.dumps(payload).encode(),
                                 headers=_headers(key, accept), method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise MetaError(_error_text(e)) from None
    except urllib.error.URLError as e:
        raise MetaError(f"Could not reach Meta Model API: {e.reason}") from None


def _need_key(secrets=None):
    key = api_key(secrets)
    if not key:
        raise MetaError("No Meta Model API key. Create one at https://dev.meta.ai/api-keys/ and add it in "
                        "Settings -> Models & keys -> Meta Model API (it is saved as MODEL_API_KEY).")
    return key


# ------------------------------------------------------------------ models and a quick check

def list_models(secrets=None, timeout=20, base=None):
    """The ids this key can call: [{"id", "owned_by"}]."""
    key = _need_key(secrets)
    req = urllib.request.Request(base_url(base) + "/models", headers=_headers(key), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise MetaError(_error_text(e)) from None
    except urllib.error.URLError as e:
        raise MetaError(f"Could not reach Meta Model API: {e.reason}") from None
    return [m for m in (d.get("data") or d.get("models") or []) if isinstance(m, dict) and m.get("id")]


def check(secrets=None, timeout=20):
    """{"ok", "detail", "models"}: does the key work, and what does it reach."""
    key = api_key(secrets)
    if not key: return {"ok": False, "detail": "No key saved yet.", "models": []}
    try:
        ids = [m["id"] for m in list_models(secrets, timeout)]
    except MetaError as e:
        return {"ok": False, "detail": str(e), "models": []}
    return {"ok": True, "detail": f"{len(ids)} models available", "models": ids}


# ------------------------------------------------------------------ Muse Image

def _data_url(path):
    ext = os.path.splitext(path)[1].lower()
    mime = IMAGE_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def _image_item(src):
    """A path, a URL or a data URL -> the {"image_url": ...} Meta takes."""
    src = str(src or "").strip()
    if src.startswith(("http://", "https://", "data:")): return {"image_url": src}
    path = os.path.expanduser(src)
    if not os.path.isfile(path): raise MetaError(f"No such image file: {src}")
    if os.path.getsize(path) > 25_000_000: raise MetaError(f"{src} is over 25 MB; shrink it first.")
    return {"image_url": _data_url(path)}


def _save_images(resp, out_dir, tag, fmt):
    rows = resp.get("data") if isinstance(resp, dict) else None
    if not rows: raise MetaError("Meta returned no image" + (f": {json.dumps(resp)[:300]}" if resp else "."))
    os.makedirs(out_dir, exist_ok=True)
    stamp, paths = int(time.time() * 1000), []
    for i, row in enumerate(rows):
        data = row.get("b64_json")
        if data:
            blob = base64.b64decode(data)
        elif row.get("url"):
            with urllib.request.urlopen(row["url"], timeout=120) as r:
                blob = r.read()
        else:
            continue
        path = os.path.join(out_dir, f"{tag}-{stamp}-{i + 1}.{fmt}")
        with open(path, "wb") as f: f.write(blob)
        paths.append(path)
    if not paths: raise MetaError("Meta's reply held no image data.")
    return paths


def generate_image(prompt, out_dir, size=None, n=1, fmt="png", secrets=None, timeout=300):
    """Muse Image: a new image from a prompt -> [file paths]. `size` ("1024x1024") only sets the
    aspect ratio; Meta renders at its own resolution."""
    key = _need_key(secrets)
    if not str(prompt or "").strip(): raise MetaError("Say what the image should show.")
    fmt = fmt if fmt in ("png", "jpeg", "webp") else "png"
    body = {"model": IMAGE_MODEL, "prompt": prompt, "n": max(1, min(int(n or 1), 4)),
            "response_format": "b64_json", "output_format": fmt}
    if size: body["size"] = str(size)
    with _post("/images/generations", body, key, timeout) as r:
        resp = json.load(r)
    return _save_images(resp, out_dir, "muse-image", fmt)


def edit_image(prompt, images, out_dir, size=None, n=1, fmt="png", secrets=None, timeout=300):
    """Muse Image: change (or combine) existing images as the prompt says -> [file paths].
    `images` are paths or URLs; several are composed into one."""
    key = _need_key(secrets)
    if not str(prompt or "").strip(): raise MetaError("Say what to change.")
    if isinstance(images, str): images = [images]
    if not images: raise MetaError("Give at least one image to edit.")
    fmt = fmt if fmt in ("png", "jpeg", "webp") else "png"
    body = {"model": IMAGE_MODEL, "prompt": prompt, "images": [_image_item(i) for i in images[:8]],
            "n": max(1, min(int(n or 1), 4)), "response_format": "b64_json", "output_format": fmt}
    if size: body["size"] = str(size)
    with _post("/images/edits", body, key, timeout) as r:
        resp = json.load(r)
    return _save_images(resp, out_dir, "muse-edit", fmt)


# ------------------------------------------------------------------ SAM 3.1
#
# The reply is text in one lane, one line per frame:
#   <0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|><|mask;x=0;y=0;data=H,W,~payload|>,1<|box...
# Boxes are read here; the mask payload (base85) is left to Meta's parser.

_FRAME = re.compile(r"<(\d+)f>")
_BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")
_MASK = re.compile(r"<\|mask;[^|]*?data=(\d+),(\d+),")


def parse_segmentation(text):
    """The lines of a SAM reply -> [{"frame", "object", "box": [x1, y1, x2, y2], "size": [w, h],
    "confidence", "mask": [rows, cols]}]. Boxes are in the media's own pixels."""
    out = []
    for line in str(text or "").splitlines():
        fm = _FRAME.match(line.strip())
        if not fm: continue
        frame = int(fm.group(1))
        body = line.strip()[fm.end():]
        # records are separated by "," between a mask's closing |> and the next object id
        for rec in re.split(r"\|>,(?=\d+<\|box)", body):
            bm = _BOX.search(rec)
            if not bm: continue
            f = dict(kv.split("=", 1) for kv in bm.group(2).split(";") if "=" in kv)
            try:
                row = {"frame": frame, "object": int(bm.group(1)),
                       "box": [int(f["x1"]), int(f["y1"]), int(f["x2"]), int(f["y2"])],
                       "size": [int(f.get("w") or 0), int(f.get("h") or 0)]}
            except (KeyError, ValueError):
                continue
            if "c" in f:
                try: row["confidence"] = round(float(f["c"]), 3)
                except ValueError: pass
            mm = _MASK.search(rec)
            if mm: row["mask"] = [int(mm.group(1)), int(mm.group(2))]
            out.append(row)
    return out


def _image_source(src):
    return _image_item(src)["image_url"]


def segment(concept, image, secrets=None, confidence=True, timeout=300):
    """SAM 3.1 on one image: every match of a short noun phrase ("yellow school bus") ->
    {"text", "objects": [parse_segmentation rows], "size": [w, h]}."""
    key = _need_key(secrets)
    concept = str(concept or "").strip()
    if not concept: raise MetaError("Name what to find, as a short noun phrase (\"duck\", \"red car\").")
    body = {"model": SAM_MODEL, "stream": True,
            "input": [{"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": concept},
                                   {"type": "input_image", "image_url": _image_source(image)}]}],
            "metadata": {"mask_encoding": "one_bit", **({"include_confidence": "true"} if confidence else {})}}
    parts, failed = [], None
    with _post("/responses", body, key, timeout, accept="text/event-stream") as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"): continue
            try: ev = json.loads(line[5:])
            except ValueError: continue
            t = ev.get("type")
            if t == "response.output_text.delta":
                parts.append(ev.get("delta") or "")
            elif t in ("response.failed", "error"):
                failed = (ev.get("response") or {}).get("error") or ev.get("error") or ev
    if failed:
        raise MetaError("SAM failed: " + (failed.get("message") if isinstance(failed, dict) else str(failed))[:400])
    text = "".join(p if p.endswith("\n") else p + "\n" for p in parts)       # one delta = one frame's line
    objs = parse_segmentation(text)
    size = next((o["size"] for o in objs if o["size"][0]), None)
    return {"text": text, "objects": objs, "size": size}


def _decode_masks(text):
    """{(frame, object): (rows-of-0/1 as a numpy array, (left, top, right, bottom))} through
    meta-sam-parser; {} without it."""
    try:
        from meta_sam_parser import CompletedOutcome, image_segmentation_format, decode_mask_to_raster
        import numpy as np
    except Exception:
        return {}
    try:
        parser = image_segmentation_format().create_parser()
        parser.push(text)
        out = {}
        for rec in parser.finish(CompletedOutcome()).result.records:
            if getattr(rec, "kind", "") != "mask": continue
            m, b = rec.mask, rec.bounds
            raster = np.frombuffer(bytes(decode_mask_to_raster(m)), dtype=np.uint8).reshape(int(m.height), int(m.width))
            out[(int(rec.identity.frame_index or 0), int(rec.identity.object_id))] = \
                (raster, (int(b.left), int(b.top), int(b.right), int(b.bottom)))
        return out
    except Exception:
        return {}


PALETTE = [(230, 57, 70), (42, 157, 143), (244, 162, 97), (69, 123, 157), (131, 56, 236), (255, 190, 11),
           (6, 214, 160), (239, 71, 111)]


def overlay(image, result, out_path):
    """The image with each match boxed and numbered (and its mask tinted when the parser is there)
    -> out_path. Needs Pillow; returns None without it."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    path = os.path.expanduser(str(image))
    if not os.path.isfile(path): return None
    im = Image.open(path).convert("RGBA")
    masks = _decode_masks(result.get("text") or "")
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i, o in enumerate(result.get("objects") or []):
        col = PALETTE[o["object"] % len(PALETTE)]
        x1, y1, x2, y2 = o["box"]
        got = masks.get((o["frame"], o["object"]))
        if got:
            raster, (bx1, by1, bx2, by2) = got
            try:
                tint = Image.fromarray((raster * 110).astype("uint8"), "L").resize((max(1, bx2 - bx1), max(1, by2 - by1)))
                layer.paste(Image.new("RGBA", tint.size, col + (255,)), (bx1, by1), tint)
            except Exception:
                pass
        draw.rectangle([x1, y1, x2, y2], outline=col + (255,), width=max(2, im.size[0] // 300))
        draw.text((x1 + 3, max(0, y1 - 12)), str(o["object"]), fill=col + (255,))
    Image.alpha_composite(im, layer).convert("RGB").save(out_path)
    return out_path

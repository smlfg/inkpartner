"""Different ways to turn ink into elements - to compare them on the same pages.

    vlm:<model chain>     whole page as one image, the model returns elements with boxes (variant B)
    lines:<model chain>   lines cut geometrically, each crop read by the model (variant A)
    ocr:tesseract         classic OCR on the rendered page (no model, local)
    ocr:apple             Apple Vision text recognition (macOS, local, no model download)

All return (subject guess, elements). OCR cannot guess the subject; it says "math" when the text has
an "=" and "prose" otherwise.
"""
from __future__ import annotations

import io

from . import agent, models, page as pagemod
from .elements import Element


def _subject_from(text: str) -> str:
    return "math" if "=" in text else "prose"


def cluster_lines(strokes: list[dict], gap: float = 0.6) -> list[list[dict]]:
    """Group strokes into lines by vertical overlap of their boxes (simple, slant-tolerant)."""
    items = []
    for s in strokes:
        ys = [p[1] for p in s["points"]]
        items.append((min(ys), max(ys), s))
    items.sort(key=lambda t: (t[0] + t[1]) / 2)
    lines: list[list] = []
    for y0, y1, s in items:
        if lines:
            ly0, ly1, ls = lines[-1]
            overlap = min(y1, ly1) - max(y0, ly0)
            if overlap > -gap * 0.3 * max(1.0, ly1 - ly0) or (y1 - y0) < 0.3 * (ly1 - ly0):
                lines[-1] = [min(ly0, y0), max(ly1, y1), ls + [s]]
                continue
        lines.append([y0, y1, [s]])
    return [l[2] for l in lines]


def read_vlm(model, strokes):
    return agent.read(model, strokes)


LINE_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}, "confidence": {"type": "number"},
                                                "legible": {"type": "boolean"}},
               "required": ["text", "confidence", "legible"], "additionalProperties": False}
LINE_PROMPT = ("Transcribe this ONE handwritten line exactly as written, even if it is wrong. Math as plain "
               "text: ^ for powers, sqrt() for roots, e.g. 3(x+2)=15. legible=false if unreadable.")


def read_lines(model, strokes):
    from . import marks
    els, texts = [], []
    for i, line in enumerate(cluster_lines([s for s in strokes if s.get("author") == "user"])):
        img = pagemod.render(line, scale=0.5)
        x0, y0, x1, y1 = marks.bbox_of(line)
        fx0 = img.info["frame"][0]
        crop = img.crop((int((x0 - fx0 - 20) * 0.5), int((y0 - 20) * 0.5),
                         int((x1 - fx0 + 20) * 0.5), int((y1 + 20) * 0.5)))
        d = model.json([pagemod.png_bytes(crop)], LINE_PROMPT, LINE_SCHEMA)
        texts.append(d["text"])
        els.append(Element(id=f"e{i}", kind="formula" if "=" in d["text"] else "line", bbox=[x0, y0, x1, y1],
                           text=d["text"], confidence=float(d["confidence"]), legible=bool(d["legible"])))
    return _subject_from(" ".join(texts)), els


def _ocr_elements(rows, frame, scale):
    """rows: [(text, confidence 0..1, (x0, y0, x1, y1) in image pixels)] -> elements in page pixels."""
    fx0 = frame[0]
    els = []
    for i, (text, conf, (x0, y0, x1, y1)) in enumerate(rows):
        bbox = [x0 / scale + fx0, y0 / scale, x1 / scale + fx0, y1 / scale]
        els.append(Element(id=f"e{i}", kind="formula" if "=" in text else "line", bbox=bbox, text=text,
                           confidence=conf, legible=conf >= 0.3))
    return els


def read_tesseract(strokes):
    import pytesseract
    img = pagemod.render([s for s in strokes if s.get("author") == "user"], scale=0.5)
    d = pytesseract.image_to_data(img, lang="deu+eng" if "deu" in pytesseract.get_languages() else "eng",
                                  output_type=pytesseract.Output.DICT)
    lines: dict = {}
    for i, word in enumerate(d["text"]):
        if not word.strip():
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, w, h, c = d["left"][i], d["top"][i], d["width"][i], d["height"][i], float(d["conf"][i])
        L = lines.setdefault(key, {"words": [], "box": [x, y, x + w, y + h], "conf": []})
        L["words"].append(word)
        b = L["box"]
        L["box"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
        L["conf"].append(max(0.0, c) / 100)
    rows = [(" ".join(L["words"]), sum(L["conf"]) / len(L["conf"]), tuple(L["box"])) for L in lines.values()]
    text = " ".join(r[0] for r in rows)
    return _subject_from(text), _ocr_elements(rows, img.info["frame"], 0.5)


def read_apple(strokes):
    from ocrmac import ocrmac
    img = pagemod.render([s for s in strokes if s.get("author") == "user"], scale=0.5)
    res = ocrmac.OCR(img, recognition_level="accurate", language_preference=["de-DE", "en-US"]).recognize()
    W, H = img.size
    rows = []
    for text, conf, (x, y, w, h) in res:            # normalised, origin bottom-left
        rows.append((text, float(conf), (x * W, (1 - y - h) * H, (x + w) * W, (1 - y) * H)))
    text = " ".join(r[0] for r in rows)
    return _subject_from(text), _ocr_elements(rows, img.info["frame"], 0.5)


def get(spec: str):
    """'vlm:ollama:qwen3.6:35b-a3b' -> callable(strokes) -> (subject, elements)"""
    kind, _, rest = spec.partition(":")
    if kind == "vlm":
        m = models.get(rest or None)
        return lambda strokes: read_vlm(m, strokes)
    if kind == "lines":
        m = models.get(rest or None)
        return lambda strokes: read_lines(m, strokes)
    if spec == "ocr:tesseract":
        return read_tesseract
    if spec == "ocr:apple":
        return read_apple
    raise ValueError(f"unknown reader {spec!r}")

"""`.rm` page in, strokes out; agent strokes appended in their own layer; page rendered to PNG.

Calibration measured by algebra-agent on the Paper Pro (2026-10-21): one document unit is one page
pixel, x = 0 is the middle of the page, y = 0 the top. The original bytes of a page are never
rewritten - agent ink is appended after them, in a layer the student can hide.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

PAGE_W, PAGE_H = 1620, 2160
AGENT_LAYER = "InkPartner Agent"
# Agent layers of the sibling projects: their ink is agent ink here too, never student content.
AGENT_LAYERS = {AGENT_LAYER, "PenEcho Agent", "Underline Agent"}
RGB = {"black": (0, 0, 0), "gray": (125, 125, 125), "red": (220, 30, 30), "green": (20, 150, 60),
       "blue": (30, 80, 210), "yellow": (230, 200, 0)}
_PEN = {"black": "BLACK", "gray": "GRAY", "red": "RED", "green": "GREEN", "blue": "BLUE", "yellow": "YELLOW"}


def to_page(x: float, y: float) -> tuple[float, float]:
    return x + PAGE_W / 2, y


def to_doc(x: float, y: float) -> tuple[float, float]:
    return x - PAGE_W / 2, y


def _layers(tree):
    from rmscene import scene_items as si

    def walk(group, label):
        for child in group.children.values():
            if isinstance(child, si.Group):
                yield from walk(child, child.label.value if child.label else label)
            elif isinstance(child, si.Line):
                yield label, child
    yield from walk(tree.root, None)


def read_strokes(path: str) -> list[dict]:
    """Every stroke on the page: points [[x, y, pressure]], colour, author ('user' | 'agent')."""
    from rmscene import read_tree
    with open(path, "rb") as f:
        tree = read_tree(f)
    out = []
    for label, line in _layers(tree):
        pts = [[*map(lambda v: round(v, 2), to_page(p.x, p.y)), round(p.pressure / 255, 3)] for p in line.points]
        if pts:
            out.append({"points": pts, "color": line.color.name.lower(),
                        "author": "agent" if label in AGENT_LAYERS else "user"})
    return out


def render(strokes: list[dict], *, width: int = PAGE_W, height: int | None = None, scale: float = 0.5,
           authors: tuple[str, ...] = ("user", "agent")) -> Image.Image:
    """Draw the strokes on white paper. The frame follows the ink on both axes: on the device a page
    is longer when scrolled and wider when zoomed out (seen 2026-10-23: x from -454 to 2099 on a
    1620 px page). A frame cut to the paper format silently drops the left edge of the writing.
    `img.info["frame"]` = [x0, y0, x1, y1] in page pixels, for mapping image boxes back to the page."""
    xs = [p[0] for s in strokes for p in s["points"]]
    ys = [p[1] for s in strokes for p in s["points"]]
    x0 = min(0, int(min(xs, default=0)) - 30)
    x1 = max(width, int(max(xs, default=0)) + 30)
    y1 = max(height or PAGE_H, int(max(ys, default=0)) + 40)
    img = Image.new("RGB", (int((x1 - x0) * scale), int(y1 * scale)), "white")
    img.info["frame"] = [x0, 0, x1, y1]
    d = ImageDraw.Draw(img)
    for s in strokes:
        if s.get("author", "user") not in authors:
            continue
        xy = [((p[0] - x0) * scale, p[1] * scale) for p in s["points"]]
        w = max(1, int(round(s.get("width", 3) * scale)))
        if len(xy) == 1:
            x, y = xy[0]
            d.ellipse([x - w, y - w, x + w, y + w], fill=RGB.get(s.get("color"), (0, 0, 0)))
        else:
            d.line(xy, fill=RGB.get(s.get("color"), (0, 0, 0)), width=w, joint="curve")
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _line_item(stroke: dict):
    from rmscene import scene_items as si
    pts = []
    for p in stroke["points"]:
        x, y = to_doc(p[0], p[1])
        pts.append(si.Point(x=x, y=y, speed=0, direction=0, width=max(1, int(round(stroke.get("width", 3) * 4))),
                            pressure=int(255 * (p[2] if len(p) > 2 else 0.7))))
    return si.Line(color=getattr(si.PenColor, _PEN.get(stroke.get("color", "black"), "BLACK")),
                   tool=si.Pen.FINELINER_2, points=pts, thickness_scale=1.0, starting_length=0.0)


def append_strokes(path_in: str, strokes: list[dict], path_out: str) -> dict:
    """path_out = original bytes + new blocks holding `strokes` in the agent layer."""
    from rmscene import read_blocks, read_tree, write_blocks, scene_items as si
    from rmscene.crdt_sequence import CrdtSequenceItem
    from rmscene.scene_stream import SceneGroupItemBlock, SceneLineItemBlock, SceneTreeBlock, TreeNodeBlock
    from rmscene.tagged_block_common import HEADER_V6, CrdtId, LwwValue

    original = open(path_in, "rb").read()
    tree = read_tree(io.BytesIO(original))
    used = [0]

    def collect(o, seen=None):
        seen = seen if seen is not None else set()
        if id(o) in seen:
            return
        seen.add(id(o))
        if isinstance(o, CrdtId):
            if o.part1 == 1:
                used.append(o.part2)
            return
        if isinstance(o, (list, tuple, set)):
            for v in o:
                collect(v, seen)
        elif isinstance(o, dict):
            for k, v in o.items():
                collect(k, seen)
                collect(v, seen)
        elif hasattr(o, "__dict__"):
            for v in vars(o).values():
                collect(v, seen)
    collect(list(read_blocks(io.BytesIO(original))))
    counter = max(used) + 1

    def new_id():
        nonlocal counter
        counter += 1
        return CrdtId(1, counter - 1)

    blocks, layer = [], None
    for child in tree.root.children.values():
        if isinstance(child, si.Group) and child.label and child.label.value == AGENT_LAYER:
            layer = child
    if layer is None:
        layer_id = new_id()
        root_keys = list(tree.root.children.keys())
        blocks += [
            SceneTreeBlock(tree_id=layer_id, node_id=CrdtId(0, 0), is_update=True, parent_id=CrdtId(0, 1)),
            TreeNodeBlock(si.Group(node_id=layer_id, label=LwwValue(timestamp=new_id(), value=AGENT_LAYER))),
            SceneGroupItemBlock(parent_id=CrdtId(0, 1), item=CrdtSequenceItem(
                item_id=new_id(), left_id=root_keys[-1] if root_keys else CrdtId(0, 0),
                right_id=CrdtId(0, 0), deleted_length=0, value=layer_id)),
        ]
        left = CrdtId(0, 0)
    else:
        layer_id = layer.node_id
        keys = list(layer.children.keys())
        left = keys[-1] if keys else CrdtId(0, 0)
    for s in strokes:
        iid = new_id()
        blocks.append(SceneLineItemBlock(parent_id=layer_id, item=CrdtSequenceItem(
            item_id=iid, left_id=left, right_id=CrdtId(0, 0), deleted_length=0, value=_line_item(s))))
        left = iid
    buf = io.BytesIO()
    write_blocks(buf, blocks)
    tail = buf.getvalue()
    assert tail.startswith(HEADER_V6)
    with open(path_out, "wb") as f:
        f.write(original + tail[len(HEADER_V6):])
    return {"original_bytes": len(original), "new_strokes": len(strokes), "layer_created": layer is None}

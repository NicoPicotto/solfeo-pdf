"""Write solfege names onto the ORIGINAL PDF, using the notehead positions
Audiveris stores in its .omr project. The score itself is never redrawn:
a note the OMR lost stays in the music, just without a name.

The .omr is a zip with one sheet#N/sheet#N.xml per page plus the binarized
page image sheet#N/BINARY.png. Pixel coordinates map to PDF points by
scaling the picture size onto the page size.
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

import pymupdf
from music21 import chord, clef, stream
from PIL import Image

from solfege import is_tie_continuation, solfege_name

FONT = "helv"
SIZE = 8.5            # pt; a name first drops to a lower line, and only shrinks if that fails
SIZES = (SIZE, 7.5, 6.5)
LINE = SIZE + 1.0     # pt between stacked lines
GAP_PT = 2.0          # below the staff's lowest ink (bottom line or lowest head)
MAX_DROP_LINES = 3    # how far a name may move down looking for free space
NUDGES_PT = (0, -2.5, 2.5)  # sideways tries at each height, centre first
COLOR = (0.08, 0.2, 0.55)
UNKNOWN = "?"         # head we cannot name (discarded by the OMR, or unmatched)


# ---------------------------------------------------------------- .omr side

def _sheet_entries(z):
    names = [n for n in z.namelist() if n.startswith("sheet#") and n.endswith(".xml")]
    return sorted(names, key=lambda n: int(n.split("#")[1].split("/")[0]))


def _overlap(a, b):
    ix = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return ix * iy / min(a["w"] * a["h"], b["w"] * b["h"])


def _head_dict(head, sheet_no, interline, **extra):
    b = head.find("bounds")
    return {
        "sheet": sheet_no, "staff": head.get("staff"), "head_id": head.get("id"),
        "pos": int(head.get("pitch")), "interline": interline,
        "x": int(b.get("x")), "y": int(b.get("y")), "w": int(b.get("w")), "h": int(b.get("h")),
        **extra,
    }


def read_omr(omr_path):
    """Returns (heads, discarded, pictures, boxes).

    heads: every notehead that made it into a voice, with the musical
      coordinates needed to find it in the MusicXML: global measure index
      (reading order == MusicXML measure order), hand (staff order in the
      system), offset in quarters, and its chord.
    discarded: heads Audiveris detected but left out of every voice (e.g. a
      triplet note it could not fit rhythmically). Candidates overlapping a
      kept head are alternatives, not lost notes, and are ignored.
    pictures: sheet number -> (width_px, height_px).
    boxes: (measure_index, hand) -> (sheet, left, top, right, bottom,
      interline) in px: the measure's span on that hand's staff.
    """
    heads, discarded, pictures, boxes = [], [], {}, {}
    measure_index = 0
    with zipfile.ZipFile(omr_path) as z:
        for name in _sheet_entries(z):
            sheet_no = int(name.split("#")[1].split("/")[0])
            root = ET.fromstring(z.read(name))
            pic = root.find("picture")
            pictures[sheet_no] = (int(pic.get("width")), int(pic.get("height")))
            interline = int(root.find("scale/interline").get("main"))
            sheet_heads = []
            for system in root.iter("system"):
                # ids are only unique among inters (measures/staves reuse small numbers)
                inters = {el.get("id"): el for el in system.find("sig/inters")}
                contains = defaultdict(list)
                for rel in system.iter("relation"):
                    if rel.find("containment") is not None:
                        contains[rel.get("source")].append(rel.get("target"))
                stacks = {st.get("id"): {sl.get("id"): Fraction(sl.get("time-offset"))
                                         for sl in st.findall("slot")}
                          for st in system.findall("stack")}
                extents = {st.get("id"): (int(st.get("left")), int(st.get("right")))
                           for st in system.findall("stack")}
                # one part with two staves, or one part per hand: staff order = hand
                parts = system.findall("part")
                staff_ids = [s.get("id") for part in parts for s in part.findall("staff")]
                system_measures = 0
                for part in parts:
                    measures = part.findall("measure")
                    system_measures = max(system_measures, len(measures))
                    for j, measure in enumerate(measures):
                        slots = stacks[measure.get("id")]
                        left, right = extents[measure.get("id")]
                        # the right barline of each staff gives that staff's height
                        for bar_id in measure.findtext("right-barline/staff-barlines", "").split():
                            bar = inters.get(bar_id)
                            if bar is not None and bar.get("staff") in staff_ids:
                                b = bar.find("bounds")
                                top = int(b.get("y"))
                                boxes[(measure_index + j, staff_ids.index(bar.get("staff")))] = (
                                    sheet_no, left, top, right, top + int(b.get("h")), interline)
                        for voice in measure.findall("voice"):
                            for entry in voice.findall("slots/entry"):
                                value = entry.find("value")
                                if value.get("status") != "BEGIN":
                                    continue
                                hc = inters[value.get("chord")]
                                for head_id in contains[hc.get("id")]:
                                    head = inters.get(head_id)
                                    if head is None or head.tag != "head":
                                        continue
                                    # head-chords sometimes lack @staff; heads always have it
                                    sheet_heads.append(_head_dict(
                                        head, sheet_no, interline,
                                        measure=measure_index + j,
                                        hand=staff_ids.index(head.get("staff")),
                                        voice=voice.get("id"),
                                        offset=slots[entry.findtext("key")] * 4,  # whole notes -> quarters
                                        chord=(sheet_no, hc.get("id")),
                                    ))
                measure_index += system_measures
                kept = {h["head_id"] for h in sheet_heads}
                for el in inters.values():
                    if el.tag == "head" and el.get("id") not in kept:
                        cand = _head_dict(el, sheet_no, interline)
                        if not any(_overlap(cand, h) > 0.5 for h in sheet_heads):
                            discarded.append(cand)
            heads += sheet_heads
    return heads, discarded, pictures, boxes


# ----------------------------------------------------------- MusicXML side

def read_score_notes(score):
    """(measure_index, hand, offset) -> [(note or chord, clef in effect)]."""
    notes = defaultdict(list)
    for hand, part in enumerate(score.parts):
        for i, m in enumerate(part.getElementsByClass(stream.Measure)):
            for e in m.recurse().notes:
                # resolve the clef now: the context is lost once we leave the score
                key = (i, hand, Fraction(e.getOffsetInHierarchy(m)).limit_denominator(64))
                notes[key].append((e, e.getContextByClass(clef.Clef)))
    return notes


def _single_notes(element):
    if isinstance(element, chord.Chord):
        return sorted(element.notes, key=lambda n: n.pitch.ps, reverse=True)
    return [element]


def expected_pos(pitch, active_clef):
    """Staff position Audiveris gives this pitch: 0 = middle line, +1 per
    step downwards."""
    return active_clef.lowestLine + 4 - pitch.diatonicNoteNum


# ---------------------------------------------------------------- matching

def match(heads, score_notes, with_octave=False):
    """Pair each head with its MusicXML note. Returns [(head, label, status)]:
    status ok / pos-mismatch (head position disagrees with the pitch) /
    unmatched; label None for a tie continuation (never named), UNKNOWN when
    the head cannot be trusted."""
    by_chord = defaultdict(list)
    for h in heads:
        by_chord[h["chord"]].append(h)
    results = []
    for chord_heads in by_chord.values():
        h0 = chord_heads[0]
        top_down = sorted(chord_heads, key=lambda h: h["y"])  # top of page = highest pitch
        best = None
        for element, active_clef in score_notes.get((h0["measure"], h0["hand"], h0["offset"]), []):
            ns = _single_notes(element)
            if len(ns) != len(top_down) or active_clef is None:
                continue
            errors = sum(expected_pos(n.pitch, active_clef) != h["pos"] for n, h in zip(ns, top_down))
            if best is None or errors < best[0]:
                best = (errors, active_clef, ns)
        if best is None:
            results += [(h, UNKNOWN, "unmatched") for h in top_down]
            continue
        _, active_clef, ns = best
        for n, h in zip(ns, top_down):
            if expected_pos(n.pitch, active_clef) != h["pos"]:
                results.append((h, UNKNOWN, "pos-mismatch"))
            else:
                label = None if is_tie_continuation(n) else solfege_name(n.pitch, with_octave)
                results.append((h, label, "ok"))
    return results


# ----------------------------------------------------------------- layout

@dataclass
class Placement:
    sheet: int
    text: str
    rect: pymupdf.Rect  # PDF points
    size: float = 0.0


class Occupancy:
    """Original ink (binarized page image, 0 = black) plus names already
    placed, in PDF points."""

    def __init__(self, ink, page_width_pt, page_height_pt):
        self.ink = ink
        self.sx = ink.width / page_width_pt
        self.sy = ink.height / page_height_pt
        self.placed = []

    def free(self, r):
        if any(r.intersects(p) for p in self.placed):
            return False
        box = (int(r.x0 * self.sx), int(r.y0 * self.sy), int(r.x1 * self.sx) + 1, int(r.y1 * self.sy) + 1)
        return self.ink.crop(box).getextrema()[0] > 0


def layout(labelled, occupancy):
    """labelled: [(head, text)]. Names go under their staff, centred on the
    head; a chord stacks high->low. A name that would touch ink or another
    name moves down (same size); if there is no room at full size it is
    made smaller, and as a last resort it is written over whatever is there.
    A name is never left out. Returns (placements, dropped, squeezed)."""
    rows = defaultdict(list)
    for h, text in labelled:
        rows[(h["sheet"], h["staff"])].append((h, text))
    placements, dropped, squeezed = [], 0, 0
    for (sheet, _), items in sorted(rows.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        occ = occupancy[sheet]
        to_pt_x = 1 / occ.sx
        to_pt_y = 1 / occ.sy
        il = items[0][0]["interline"]
        # middle staff line from each head: centre_y = middle_y + pos * il/2
        middles = sorted(h["y"] + h["h"] / 2 - h["pos"] * il / 2 for h, _ in items)
        bottom_line = middles[len(middles) // 2] + 2 * il
        lowest_head = max(h["y"] + h["h"] for h, _ in items)
        baseline_top = max(bottom_line, lowest_head) * to_pt_y + GAP_PT
        columns = defaultdict(list)
        for h, text in items:
            columns[h.get("chord", ("solo", h["head_id"]))].append((h, text))
        for col in sorted(columns.values(), key=lambda c: min(h["x"] for h, _ in c)):
            col.sort(key=lambda t: t[0]["y"])
            cx = sum(h["x"] + h["w"] / 2 for h, _ in col) / len(col) * to_pt_x
            next_top = baseline_top
            for h, text in col:
                rect, size, forced = _find_spot(occ, text, cx, next_top)
                occ.placed.append(rect)
                placements.append(Placement(sheet, text, rect, size))
                dropped += rect.y0 > next_top and size == SIZE
                squeezed += size < SIZE or forced
                next_top = rect.y0 + LINE
    return placements, dropped, squeezed


def _find_spot(occ, text, cx, top):
    """First free rect: at full size, then smaller sizes; each time going
    down in half-line steps and trying the exact centre first, then a small
    nudge sideways. No free spot at all: the smallest size, right under the
    note, overlapping whatever is there."""
    for size in SIZES:
        width = pymupdf.get_text_length(text, fontname=FONT, fontsize=size)
        for step in range(2 * MAX_DROP_LINES + 1):
            y = top + step * LINE / 2
            for dx in NUDGES_PT:
                rect = pymupdf.Rect(cx + dx - width / 2, y, cx + dx + width / 2, y + size)
                if occ.free(rect):
                    return rect, size, False
    size = SIZES[-1]
    width = pymupdf.get_text_length(text, fontname=FONT, fontsize=size)
    return pymupdf.Rect(cx - width / 2, top, cx + width / 2, top + size), size, True


# ------------------------------------------------------------- measure marks

MARK_COLOR = (1.0, 0.86, 0.55)  # soft amber, drawn UNDER the music
MARK_PAD_IL = 0.6               # vertical padding around the staff, in interlines


def mark_rects(boxes, doubtful, page_sizes, pictures):
    """PDF rects (sheet, Rect) for doubtful (measure_index, hand) pairs.
    hand None marks both staves of that measure."""
    rects = []
    for measure_index, hand in doubtful:
        hands = (0, 1) if hand is None else (hand,)
        for hd in hands:
            box = boxes.get((measure_index, hd))
            if box is None:
                continue
            sheet, left, top, right, bottom, il = box
            sx = page_sizes[sheet][0] / pictures[sheet][0]
            sy = page_sizes[sheet][1] / pictures[sheet][1]
            pad = MARK_PAD_IL * il
            rects.append((sheet, pymupdf.Rect(left * sx, (top - pad) * sy, right * sx, (bottom + pad) * sy)))
    return rects


# ------------------------------------------------------------------ public

@dataclass
class OverlayStats:
    named: int
    unknown: int
    dropped: int
    squeezed: int
    pos_mismatch: int
    unmatched: int
    discarded: int
    marked: int


def overlay(pdf_in, omr_path, score, pdf_out, with_octave=False, doubtful=()):
    """doubtful: [(measure_index, hand or None)] to highlight."""
    heads, discarded, pictures, boxes = read_omr(omr_path)
    results = match(heads, read_score_notes(score), with_octave)
    labelled = [(h, text) for h, text, _ in results if text]
    labelled += [(h, UNKNOWN) for h in discarded]

    doc = pymupdf.open(pdf_in)
    occupancy = {}
    with zipfile.ZipFile(omr_path) as z:
        for sheet in pictures:
            ink = Image.open(io.BytesIO(z.read(f"sheet#{sheet}/BINARY.png"))).convert("L")
            page = doc[sheet - 1]
            occupancy[sheet] = Occupancy(ink, page.rect.width, page.rect.height)

    page_sizes = {s: (doc[s - 1].rect.width, doc[s - 1].rect.height) for s in pictures}
    marks = mark_rects(boxes, doubtful, page_sizes, pictures)
    for sheet, rect in marks:
        # overlay=False puts the fill behind the original content
        doc[sheet - 1].draw_rect(rect, color=None, fill=MARK_COLOR, overlay=False)

    placements, dropped, squeezed = layout(labelled, occupancy)
    for p in placements:
        doc[p.sheet - 1].insert_text((p.rect.x0, p.rect.y1 - p.size * 0.18), p.text,
                                      fontname=FONT, fontsize=p.size, color=COLOR)
    doc.save(pdf_out, garbage=3, deflate=True)

    return OverlayStats(
        named=sum(1 for p in placements if p.text != UNKNOWN),
        unknown=sum(1 for p in placements if p.text == UNKNOWN),
        dropped=dropped, squeezed=squeezed,
        pos_mismatch=sum(1 for *_, s in results if s == "pos-mismatch"),
        unmatched=sum(1 for *_, s in results if s == "unmatched"),
        discarded=len(discarded),
        marked=len(marks),
    )

"""Tests for writing names onto the original PDF: reading the .omr,
matching heads to MusicXML notes, and placing the names.

Uses a tiny synthetic .omr (no copyrighted scores in the repo)."""

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402
from music21 import chord, clef, meter, note, stream, tie  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from overlay import SIZES, UNKNOWN, Occupancy, layout, mark_rects, match, read_omr, read_score_notes  # noqa: E402

IL = 20  # interline in px


def head_xml(hid, staff, pos, x, y, w=22, h=18):
    return (f'<head pitch="{pos}" shape="NOTEHEAD_BLACK" grade="0.8" staff="{staff}" id="{hid}">'
            f'<bounds x="{x}" y="{y}" w="{w}" h="{h}"/></head>')


def sheet_xml(heads, chords, slots_by_measure, parts, stack_offsets, extra_heads=""):
    """heads: xml; chords: {chord_id: [head_ids]}; slots_by_measure:
    {measure_id: {voice: [(slot_key, chord_id)]}}; parts: [[staff ids]]."""
    chord_xml = "".join(f'<head-chord grade="0.9" id="{c}"><bounds x="0" y="0" w="1" h="1"/></head-chord>'
                        for c in chords)
    rels = "".join(f'<relation source="{c}" target="{h}"><containment/></relation>'
                   for c, hs in chords.items() for h in hs)
    stacks = "".join(
        f'<stack id="{mid}" left="50" right="300">' + "".join(f'<slot id="{k}" time-offset="{off}"/>' for k, off in offs.items()) + "</stack>"
        for mid, offs in stack_offsets.items())
    parts_xml = ""
    for staff_ids in parts:
        measures = ""
        for mid, voices in slots_by_measure.items():
            vx = ""
            for voice, entries in voices.items():
                if not any(any(h_staff(chords, c, heads) in staff_ids for c in [cid]) for _, cid in entries):
                    continue
                vx += f'<voice id="{voice}"><slots>' + "".join(
                    f'<entry><key>{k}</key><value chord="{c}" status="BEGIN"/></entry>' for k, c in entries
                ) + "</slots></voice>"
            bars = " ".join(str(BARLINES[s]) for s in staff_ids)
            measures += (f'<measure id="{mid}"><right-barline><staff-barlines>{bars}</staff-barlines>'
                         f'</right-barline>{vx}</measure>')
        parts_xml += "<part>" + "".join(f'<staff id="{s}"/>' for s in staff_ids) + measures + "</part>"
    return (
        '<sheet><picture width="1000" height="1000"/><scale><interline main="20"/></scale>'
        f'<page><system id="1"><sig><inters>{heads}{extra_heads}{chord_xml}{BARLINE_XML}</inters>'
        f'<relations>{rels}</relations></sig>{stacks}{parts_xml}</system></page></sheet>'
    )


# right barline of each staff: its bounds give the staff's height
BARLINES = {"1": 50, "2": 51}
BARLINE_XML = ('<staff-barline staff="1" id="50"><bounds x="298" y="160" w="3" h="81"/></staff-barline>'
               '<staff-barline staff="2" id="51"><bounds x="298" y="360" w="3" h="81"/></staff-barline>')


def h_staff(chords, cid, heads_xml):
    first = chords[cid][0]
    marker = f'id="{first}"'
    seg = heads_xml[: heads_xml.index(marker)]
    return seg[seg.rindex('staff="') + 7:].split('"')[0]


def write_omr(path, sheets):
    """Each synthetic sheet holds one measure with local id 10; book.xml says
    each page has 1 measure, so sheet n's measure is number 10 + (n - 1)."""
    blank = io.BytesIO()
    Image.new("L", (1000, 1000), 255).save(blank, format="PNG")
    book = "<book>" + "".join(f'<sheet number="{n}"><page id="1" delta-measure-id="1"/></sheet>'
                              for n in range(1, len(sheets) + 1)) + "</book>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("book.xml", book)
        for n, xml in enumerate(sheets, start=1):
            z.writestr(f"sheet#{n}/sheet#{n}.xml", xml)
            z.writestr(f"sheet#{n}/BINARY.png", blank.getvalue())


def score_one_measure(n_measures=1, numbers=None):
    """RH: chord F#4+A4 (beat 1), G4 tied over beats 2-3. LH: D3 dotted half.
    Measures are numbered 10, 11, ... like the synthetic .omr."""
    numbers = numbers or [10 + i for i in range(n_measures)]
    rh, lh = stream.Part(), stream.Part()
    for i, number in enumerate(numbers):
        m = stream.Measure(number=number)
        if i == 0:
            m.append([clef.TrebleClef(), meter.TimeSignature("3/4")])
        g1, g2 = note.Note("G4"), note.Note("G4")
        g1.tie, g2.tie = tie.Tie("start"), tie.Tie("stop")
        m.append([chord.Chord(["F#4", "A4"]), g1, g2])
        rh.append(m)
        ml = stream.Measure(number=number)
        if i == 0:
            ml.append([clef.BassClef(), meter.TimeSignature("3/4")])
        ml.append(note.Note("D3", quarterLength=3))
        lh.append(ml)
    s = stream.Score()
    s.insert(0, rh)
    s.insert(0, lh)
    return s


# Treble: middle line B4 = pos 0, A4 = 1, G4 = 2, F#4 = 3. Bass: middle line D3 = 0.
HEADS = (head_xml(10, 1, 1, 100, 191) + head_xml(11, 1, 3, 100, 211)
         + head_xml(12, 1, 2, 160, 201) + head_xml(13, 1, 2, 220, 201)
         + head_xml(20, 2, 0, 100, 391))
CHORDS = {100: [10, 11], 101: [12], 102: [13], 200: [20]}
# measure/stack id 10 on purpose: collides with head id 10
SLOTS = {10: {"1": [("1", 100), ("2", 101), ("3", 102)], "5": [("1", 200)]}}
STACK = {10: {"1": "0", "2": "1/4", "3": "1/2"}}


def labels_by_head(results):
    return {h["head_id"]: (text, status) for h, text, status in results}


class ReadAndMatchTest(unittest.TestCase):
    def run_match(self, sheets, score, parts=None):
        with tempfile.TemporaryDirectory() as tmp:
            omr = Path(tmp) / "t.omr"
            write_omr(omr, sheets)
            heads, discarded, pictures, boxes = read_omr(omr)
        self.boxes = boxes
        return heads, discarded, pictures, match(heads, read_score_notes(score))

    def test_one_part_two_staves(self):
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK)
        heads, discarded, pictures, results = self.run_match([sheet], score_one_measure())
        self.assertEqual(pictures, {1: (1000, 1000)})
        self.assertEqual(discarded, [])
        self.assertEqual(labels_by_head(results), {
            "10": ("La", "ok"), "11": ("Fa#", "ok"),   # chord: top head = highest note
            "12": ("Sol", "ok"),
            "13": (None, "ok"),                         # tie continuation: not named
            "20": ("Re", "ok"),                         # left hand, bass clef
        })
        hands = {h["head_id"]: h["hand"] for h in heads}
        self.assertEqual((hands["10"], hands["20"]), (0, 1))

    def test_one_part_per_hand(self):
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1"], ["2"]], STACK)
        *_, results = self.run_match([sheet], score_one_measure())
        self.assertEqual(labels_by_head(results)["20"], ("Re", "ok"))
        self.assertEqual(labels_by_head(results)["10"], ("La", "ok"))

    def test_chord_ids_repeat_across_sheets(self):
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK)
        heads, _, _, results = self.run_match([sheet, sheet], score_one_measure(2))
        self.assertEqual(sorted({h["measure"] for h in heads}), [10, 11])
        self.assertTrue(all(status == "ok" for _, _, status in results))
        self.assertEqual(len(results), 10)

    def test_measure_not_exported_does_not_shift_the_rest(self):
        # Audiveris found measures 10 and 11 but exported only 11 (as with
        # "Error visiting Measure"): 11 must still get its own names.
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK)
        heads, _, _, results = self.run_match([sheet, sheet], score_one_measure(numbers=[11]))
        by_measure = {}
        for h, text, status in results:
            by_measure.setdefault(h["measure"], set()).add(status)
        self.assertEqual(by_measure, {10: {"unmatched"}, 11: {"ok"}})

    def test_courtesy_pseudo_measure_is_skipped(self):
        # As Audiveris writes it: at the end of the system, a CAUTIONARY stack
        # reusing the last stack's id, with no slots, and a measure "10C"
        # whose voices still list slot keys. Not a measure of the score.
        courtesy = ('<stack id="10" left="300" right="330" special="CAUTIONARY" expected="1" duration="0"/>'
                    '</system>')
        courtesy_measure = ('<measure id="10C"><voice id="1"><slots><entry><key>1</key>'
                            '<value chord="100" status="BEGIN"/></entry></slots></voice></measure></part>')
        first = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK)
        first = first.replace("</part>", courtesy_measure, 1).replace("</system>", courtesy, 1)
        # the courtesy stack comes after the real one, so it would win a plain id lookup
        self.assertLess(first.index('<stack id="10" left="50"'), first.index('special="CAUTIONARY"'))
        second = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK)
        heads, _, _, results = self.run_match([first, second], score_one_measure(2))
        self.assertEqual(sorted({h["measure"] for h in heads}), [10, 11])
        self.assertEqual(len(results), 10)
        self.assertTrue(all(status == "ok" for _, _, status in results))
        self.assertEqual(self.boxes[(10, 0)][1:4], (50, 160, 300))

    def test_discarded_head_is_reported_but_duplicates_are_not(self):
        lost = head_xml(30, 1, 1, 400, 191)        # not in any voice, alone
        duplicate = head_xml(31, 1, 2, 161, 202)   # alternative over kept head 12
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], STACK, extra_heads=lost + duplicate)
        _, discarded, _, _ = self.run_match([sheet], score_one_measure())
        self.assertEqual([d["head_id"] for d in discarded], ["30"])

    def test_position_disagreeing_with_pitch_gets_question_mark(self):
        wrong = HEADS.replace('pitch="2" shape="NOTEHEAD_BLACK" grade="0.8" staff="1" id="12"',
                              'pitch="-4" shape="NOTEHEAD_BLACK" grade="0.8" staff="1" id="12"')
        sheet = sheet_xml(wrong, CHORDS, SLOTS, [["1", "2"]], STACK)
        *_, results = self.run_match([sheet], score_one_measure())
        self.assertEqual(labels_by_head(results)["12"], (UNKNOWN, "pos-mismatch"))

    def test_head_without_musicxml_note_gets_question_mark(self):
        stack = {10: {"1": "0", "2": "1/8", "3": "1/2"}}  # slot 2 at a time with no note
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, [["1", "2"]], stack)
        *_, results = self.run_match([sheet], score_one_measure())
        self.assertEqual(labels_by_head(results)["12"], (UNKNOWN, "unmatched"))


def head(hid, x, pos, staff="1", chord_id=None, middle_y=200, w=20, h=16):
    cy = middle_y + pos * IL / 2
    return {"sheet": 1, "staff": staff, "head_id": str(hid), "pos": pos, "interline": IL,
            "x": x, "y": int(cy - h / 2), "w": w, "h": h, "chord": chord_id or ("c", hid)}


def occupancy(ink_rects=()):
    img = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(img)
    for r in ink_rects:
        draw.rectangle(r, fill=0)
    return {1: Occupancy(img, 1000, 1000)}  # 1 px == 1 pt to keep numbers readable


class LayoutTest(unittest.TestCase):
    def test_name_is_centred_below_the_staff(self):
        (p,), dropped, squeezed = layout([(head(1, 100, 0), "Do")], occupancy())
        self.assertAlmostEqual((p.rect.x0 + p.rect.x1) / 2, 110, delta=0.5)
        self.assertGreater(p.rect.y0, 240)  # bottom staff line: middle 200 + 2 interlines
        self.assertEqual((dropped, squeezed), (0, 0))

    def test_chord_stacks_high_to_low(self):
        top, low = head(1, 100, -2, chord_id="c"), head(2, 100, 2, chord_id="c")
        placements, *_ = layout([(low, "Mi"), (top, "Sol")], occupancy())
        by_text = {p.text: p.rect for p in placements}
        self.assertLess(by_text["Sol"].y1, by_text["Mi"].y0 + 0.01)
        self.assertAlmostEqual(by_text["Sol"].x0 + by_text["Sol"].width / 2,
                               by_text["Mi"].x0 + by_text["Mi"].width / 2, delta=0.5)

    def test_close_notes_never_overlap(self):
        items = [(head(i, 100 + i * 8, 0), "Fa#") for i in range(4)]
        placements, dropped, squeezed = layout(items, occupancy())
        rects = [p.rect for p in placements]
        self.assertEqual(len(rects), 4)
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a.intersects(b))
        self.assertGreater(dropped, 0)
        self.assertEqual(squeezed, 0)

    def test_avoids_original_ink(self):
        ink = (90, 240, 140, 260)  # e.g. a dynamic right under the note
        (p,), dropped, _ = layout([(head(1, 100, 0), "Re")], occupancy([ink]))
        self.assertFalse(p.rect.intersects(pymupdf.Rect(ink)))
        self.assertEqual(dropped, 1)

    def test_name_is_never_left_out(self):
        crowded = occupancy([(0, 240, 1000, 400)])  # no free spot anywhere below the staff
        (p,), _, squeezed = layout([(head(1, 100, 0), "Re")], crowded)
        self.assertEqual((p.text, p.size, squeezed), ("Re", SIZES[-1], 1))
        self.assertAlmostEqual((p.rect.x0 + p.rect.x1) / 2, 110, delta=0.5)  # still under its note

    def test_shrinks_before_overlapping(self):
        # room for a small name only: a gap 7 pt tall right under the staff
        ink = [(0, 249, 1000, 400)]  # baseline starts at 242
        (p,), _, squeezed = layout([(head(1, 100, 0), "Re")], occupancy(ink))
        self.assertLess(p.size, SIZES[0])
        self.assertTrue(occupancy(ink)[1].free(p.rect))
        self.assertEqual(squeezed, 1)

    def test_each_staff_has_its_own_row(self):
        rh = head(1, 100, 0, staff="1", middle_y=200)
        lh = head(2, 100, 0, staff="2", middle_y=400)
        placements, *_ = layout([(rh, "Si"), (lh, "Re")], occupancy())
        by_text = {p.text: p.rect for p in placements}
        self.assertLess(by_text["Si"].y1, 360)   # between the staves
        self.assertGreater(by_text["Re"].y0, 440)  # below the left-hand staff


class MeasureMarkTest(unittest.TestCase):
    def read_boxes(self, parts):
        sheet = sheet_xml(HEADS, CHORDS, SLOTS, parts, STACK)
        with tempfile.TemporaryDirectory() as tmp:
            omr = Path(tmp) / "t.omr"
            write_omr(omr, [sheet])
            *_, pictures, boxes = read_omr(omr)
        return pictures, boxes

    def test_box_per_measure_and_hand(self):
        for parts in ([["1", "2"]], [["1"], ["2"]]):
            _, boxes = self.read_boxes(parts)
            self.assertEqual(boxes[(10, 0)], (1, 50, 160, 300, 241, IL))
            self.assertEqual(boxes[(10, 1)], (1, 50, 360, 300, 441, IL))

    def test_rects_scaled_to_the_page_with_padding(self):
        pictures, boxes = self.read_boxes([["1", "2"]])
        (sheet, r), = mark_rects(boxes, [(10, 1)], {1: (500, 500)}, pictures)  # page = half the picture
        self.assertEqual(sheet, 1)
        self.assertEqual((r.x0, r.x1), (25, 150))
        self.assertLess(r.y0, 180)
        self.assertGreater(r.y1, 220.5)

    def test_hand_none_marks_both_staves(self):
        pictures, boxes = self.read_boxes([["1", "2"]])
        self.assertEqual(len(mark_rects(boxes, [(10, None)], {1: (1000, 1000)}, pictures)), 2)


if __name__ == "__main__":
    unittest.main()

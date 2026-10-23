"""Name a notehead from what is drawn on the page alone: its line/space,
the clef and key signature in effect on its staff, the accidentals
Audiveris attached to heads, and ties. Used for heads Audiveris detected
but could not export to MusicXML (typically measures whose rhythm it could
not resolve), so they get a name instead of a "?".

Same rules as solfege.py: the alteration that sounds (key signature, then
accidentals still in force in the measure), and only the first note of a
tie is named.
"""

import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

from music21 import pitch

from solfege import solfege_name

# diatonic number (music21: C4 = 29) of the note on the clef's reference line
CLEF_REFERENCE = {"G": 33, "F": 25, "C": 29}  # G4, F3, C4
CLEF_OCTAVE = (("15MA", 14), ("8VA", 7), ("15MB", -14), ("8VB", -7))
ALTER = {"SHARP": 1, "FLAT": -1, "NATURAL": 0, "DOUBLE_SHARP": 2, "DOUBLE_FLAT": -2}


def _clef_middle(clef):
    """Diatonic number of the staff's middle line under this clef, or None."""
    shape = clef.get("shape", "")
    base = CLEF_REFERENCE.get(shape[:1])
    if base is None:
        return None
    for marker, steps in CLEF_OCTAVE:
        if marker in shape:
            base += steps
            break
    # the clef's own position (e.g. G clef on pos 2): middle line is that many steps higher
    return base + int(clef.get("pitch"))


def _x(el):
    return int(el.find("bounds").get("x"))


def _key_alter(fifths, step):
    order_sharps = "FCGDAEB"
    if fifths > 0:
        return 1 if step in order_sharps[:fifths] else 0
    if fifths < 0:
        return -1 if step in order_sharps[::-1][:-fifths] else 0
    return 0


def geometric_names(omr_path, with_octave=False):
    """(sheet, head_id) -> name, None for a tie continuation (not named),
    for every head on every page. Heads whose clef cannot be told are left
    out."""
    names = {}
    clef_by_hand, key_by_hand = {}, defaultdict(int)  # carried from system to system
    with zipfile.ZipFile(omr_path) as z:
        entries = sorted((n for n in z.namelist() if n.startswith("sheet#") and n.endswith(".xml")),
                         key=lambda n: int(n.split("#")[1].split("/")[0]))
        for name in entries:
            sheet_no = int(name.split("#")[1].split("/")[0])
            root = ET.fromstring(z.read(name))
            for system in root.iter("system"):
                inters = list(system.find("sig/inters"))
                by_id = {el.get("id"): el for el in inters}
                staff_ids = [s.get("id") for part in system.findall("part") for s in part.findall("staff")]
                hand_of = {s: i for i, s in enumerate(staff_ids)}
                stacks = sorted((int(st.get("left")), int(st.get("right")))
                                for st in system.findall("stack") if st.get("special") != "CAUTIONARY")

                accidental_of, continuation = {}, set()
                for rel in system.iter("relation"):
                    kind = rel[0].tag
                    src, dst = by_id.get(rel.get("source")), by_id.get(rel.get("target"))
                    if kind == "alter-head" and src is not None and src.get("shape") in ALTER:
                        accidental_of[rel.get("target")] = ALTER[src.get("shape")]
                    elif (kind == "slur-head" and src is not None and src.get("tie") == "true"
                          and rel[0].get("side") == "RIGHT"):
                        continuation.add(rel.get("target"))

                # clef / key changes along each staff, in x order
                clefs, keys = defaultdict(list), defaultdict(list)
                for el in inters:
                    staff = el.get("staff")
                    if el.tag == "clef" and staff in hand_of and _clef_middle(el) is not None:
                        clefs[staff].append((_x(el), _clef_middle(el)))
                    elif el.tag == "key" and staff in hand_of and el.get("fifths") is not None:
                        keys[staff].append((_x(el), int(el.get("fifths"))))
                for lst in (*clefs.values(), *keys.values()):
                    lst.sort()

                heads = sorted((el for el in inters if el.tag == "head" and el.get("staff") in hand_of), key=_x)
                in_force = {}  # (staff, measure, diatonic) -> alter set by an accidental earlier in the bar
                for head in heads:
                    staff, x = head.get("staff"), _x(head)
                    hand = hand_of[staff]
                    middle = next((m for cx, m in reversed(clefs[staff]) if cx <= x), clef_by_hand.get(hand))
                    if middle is None:
                        continue
                    fifths = next((f for kx, f in reversed(keys[staff]) if kx <= x), key_by_hand[hand])
                    diatonic = middle - int(head.get("pitch"))
                    measure = next((i for i, (l, r) in enumerate(stacks) if l <= x < r), None)
                    p = pitch.Pitch()
                    p.diatonicNoteNum = diatonic
                    key = (staff, measure, diatonic)
                    if head.get("id") in accidental_of:
                        alter = accidental_of[head.get("id")]
                        in_force[key] = alter
                    elif key in in_force:
                        alter = in_force[key]
                    else:
                        alter = _key_alter(fifths, p.step)
                    if alter:
                        p.accidental = pitch.Accidental(alter)
                    names[(sheet_no, head.get("id"))] = (
                        None if head.get("id") in continuation else solfege_name(p, with_octave))

                # what is in force at the end of this system carries to the next one
                for staff, hand in hand_of.items():
                    if clefs[staff]:
                        clef_by_hand[hand] = clefs[staff][-1][1]
                    if keys[staff]:
                        key_by_hand[hand] = keys[staff][-1][1]
    return names

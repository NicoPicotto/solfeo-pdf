"""Tests for naming a notehead from the page alone (clef, key, accidentals,
ties), used when Audiveris could not export it to MusicXML."""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geometry import geometric_names  # noqa: E402


def bounds(x, y=100):
    return f'<bounds x="{x}" y="{y}" w="20" h="16"/>'


def head(hid, staff, pos, x):
    return f'<head pitch="{pos}" shape="NOTEHEAD_BLACK" staff="{staff}" id="{hid}">{bounds(x)}</head>'


def clef(cid, staff, shape, pos, x):
    return f'<clef shape="{shape}" pitch="{pos}" staff="{staff}" id="{cid}">{bounds(x)}</clef>'


TREBLE = ("G_CLEF", 2)
BASS = ("F_CLEF", -2)


def key(kid, staff, fifths, x):
    return f'<key fifths="{fifths}" staff="{staff}" id="{kid}">{bounds(x)}</key>'


def alter(aid, staff, shape, x):
    return f'<alter shape="{shape}" pitch="0" staff="{staff}" id="{aid}">{bounds(x)}</alter>'


def rel(src, dst, kind, **attrs):
    a = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f'<relation source="{src}" target="{dst}"><{kind}{a}/></relation>'


def system(inters, relations="", stacks=((0, 500), (500, 1000)), staves=("1", "2")):
    stack_xml = "".join(f'<stack id="{i + 1}" left="{l}" right="{r}"/>' for i, (l, r) in enumerate(stacks))
    staff_xml = "".join(f'<staff id="{s}"/>' for s in staves)
    return (f'<system><sig><inters>{inters}</inters><relations>{relations}</relations></sig>'
            f'{stack_xml}<part>{staff_xml}</part></system>')


def names(*systems):
    xml = f'<sheet><page>{"".join(systems)}</page></sheet>'
    with tempfile.TemporaryDirectory() as tmp:
        omr = Path(tmp) / "t.omr"
        with zipfile.ZipFile(omr, "w") as z:
            z.writestr("sheet#1/sheet#1.xml", xml)
        return {hid: name for (_, hid), name in geometric_names(omr).items()}


HEADER = clef(1, "1", *TREBLE, 10) + clef(2, "2", *BASS, 10)


class GeometricNamesTest(unittest.TestCase):
    def test_line_and_space_under_each_clef(self):
        # treble: middle line Si4, pos +3 Fa4, pos -5 Sol5; bass: middle line Re3, pos +4 Sol2
        got = names(system(HEADER + head(10, "1", 0, 100) + head(11, "1", 3, 120) + head(12, "1", -5, 140)
                           + head(20, "2", 0, 100) + head(21, "2", 4, 120)))
        self.assertEqual(got, {"10": "Si", "11": "Fa", "12": "Sol", "20": "Re", "21": "Sol"})

    def test_key_signature(self):
        # one sharp: every Fa is Fa#, other notes untouched
        got = names(system(HEADER + key(3, "1", 1, 40) + key(4, "2", -1, 40)
                           + head(10, "1", 3, 100) + head(11, "1", 0, 120) + head(20, "2", 1, 100)))
        self.assertEqual(got, {"10": "Fa#", "11": "Si", "20": "Do"})
        got = names(system(HEADER + key(4, "2", -1, 40) + head(20, "2", -5, 100)))  # Re3 + 5 steps = Si3
        self.assertEqual(got, {"20": "Sib"})

    def test_accidental_lasts_until_the_barline(self):
        inters = (HEADER + alter(5, "1", "SHARP", 95) + head(10, "1", 2, 100)   # Sol#
                  + head(11, "1", 2, 200)                                       # still Sol# in the bar
                  + head(12, "1", 2, 600))                                      # next bar: Sol
        got = names(system(inters, rel(5, 10, "alter-head")))
        self.assertEqual(got, {"10": "Sol#", "11": "Sol#", "12": "Sol"})

    def test_accidental_only_affects_the_same_octave(self):
        inters = HEADER + alter(5, "1", "FLAT", 95) + head(10, "1", 0, 100) + head(11, "1", -7, 200)
        got = names(system(inters, rel(5, 10, "alter-head")))
        self.assertEqual(got, {"10": "Sib", "11": "Si"})

    def test_natural_cancels_the_key_signature(self):
        inters = (HEADER + key(3, "1", 1, 40) + alter(5, "1", "NATURAL", 95)
                  + head(10, "1", 3, 100) + head(11, "1", 3, 200))
        got = names(system(inters, rel(5, 10, "alter-head")))
        self.assertEqual(got, {"10": "Fa", "11": "Fa"})

    def test_tie_continuation_is_not_named(self):
        inters = (HEADER + head(10, "1", 0, 100) + head(11, "1", 0, 200)
                  + '<slur tie="true" id="6"><bounds x="100" y="90" w="100" h="5"/></slur>'
                  + '<slur tie="false" id="7"><bounds x="100" y="90" w="100" h="5"/></slur>'
                  + head(12, "1", 1, 300))
        relations = (rel(6, 10, "slur-head", side="LEFT") + rel(6, 11, "slur-head", side="RIGHT")
                     + rel(7, 11, "slur-head", side="LEFT") + rel(7, 12, "slur-head", side="RIGHT"))
        got = names(system(inters, relations))
        self.assertEqual(got, {"10": "Si", "11": None, "12": "La"})  # a plain slur does not hide 12

    def test_clef_change_in_the_middle_of_a_system(self):
        inters = HEADER + head(10, "1", 0, 100) + clef(8, "1", "F_CLEF_SMALL", -2, 300) + head(11, "1", 0, 400)
        self.assertEqual(names(system(inters)), {"10": "Si", "11": "Re"})

    def test_clef_and_key_carry_to_the_next_system(self):
        first = system(HEADER + key(3, "1", 2, 40) + head(10, "1", 6, 100))       # Do#4
        second = system(head(30, "1", 6, 100))                                     # no clef/key drawn
        self.assertEqual(names(first, second), {"10": "Do#", "30": "Do#"})


if __name__ == "__main__":
    unittest.main()

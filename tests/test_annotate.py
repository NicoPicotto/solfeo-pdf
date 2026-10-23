import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music21 import converter, stream  # noqa: E402

from annotate import annotate  # noqa: E402
from solfege import note_labels  # noqa: E402


def note(step, octave, dur, typ, alter=None, acc=None, chord=False, tie=None, staff=1, voice=1):
    alter_xml = f"<alter>{alter}</alter>" if alter is not None else ""
    tie_xml = f'<tie type="{tie}"/>' if tie else ""
    tied_xml = f'<notations><tied type="{tie}"/></notations>' if tie else ""
    acc_xml = f"<accidental>{acc}</accidental>" if acc else ""
    return (
        f"<note>{'<chord/>' if chord else ''}"
        f"<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
        f"<duration>{dur}</duration>{tie_xml}<voice>{voice}</voice><type>{typ}</type>"
        f"{acc_xml}<staff>{staff}</staff>{tied_xml}</note>"
    )


def rest(dur, typ, staff, voice):
    return f"<note><rest/><duration>{dur}</duration><voice>{voice}</voice><type>{typ}</type><staff>{staff}</staff></note>"


def backup(dur):
    return f"<backup><duration>{dur}</duration></backup>"


# D major (F#, C#), 4/4, divisions=2. <alter> holds the sounding pitch, as
# Audiveris/MuseScore write it, whether or not an accidental is displayed.
MEASURES = [
    # m1: key-signature sharp, explicit sharp, same sharp carried in the measure, flat
    note("F", 4, 2, "quarter", alter=1)
    + note("G", 4, 2, "quarter", alter=1, acc="sharp")
    + note("G", 4, 2, "quarter", alter=1)
    + note("B", 4, 2, "quarter", alter=-1, acc="flat")
    + backup(8)
    + note("D", 3, 8, "whole", staff=2, voice=5),
    # m2: accidental cancelled by barline, chord, tie start; LH rest + chord with tie start
    note("G", 4, 2, "quarter")
    + note("D", 4, 2, "quarter")
    + note("F", 4, 2, "quarter", alter=1, chord=True)
    + note("A", 4, 2, "quarter", chord=True)
    + note("E", 4, 4, "half", tie="start")
    + backup(8)
    + rest(4, "half", staff=2, voice=5)
    + note("A", 2, 4, "half", staff=2, voice=5)
    + note("E", 3, 4, "half", chord=True, tie="start", staff=2, voice=5),
    # m3: tie stop, double sharp, double flat; LH chord where only one note is tied over
    note("E", 4, 4, "half", tie="stop")
    + note("F", 4, 2, "quarter", alter=2, acc="double-sharp")
    + note("B", 4, 2, "quarter", alter=-2, acc="flat-flat")
    + backup(8)
    + note("A", 2, 8, "whole", staff=2, voice=5)
    + note("E", 3, 8, "whole", chord=True, tie="stop", staff=2, voice=5),
]

ATTRIBUTES = (
    "<attributes><divisions>2</divisions><key><fifths>2</fifths></key>"
    "<time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves>"
    "<clef number='1'><sign>G</sign><line>2</line></clef>"
    "<clef number='2'><sign>F</sign><line>4</line></clef></attributes>"
)

SCORE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name>'
    '</score-part></part-list><part id="P1">'
    + "".join(
        f'<measure number="{i}">{ATTRIBUTES if i == 1 else ""}{body}</measure>'
        for i, body in enumerate(MEASURES, start=1)
    )
    + "</part></score-partwise>"
)

EXPECTED = {
    "RH": {
        1: [["Fa#"], ["Sol#"], ["Sol#"], ["Sib"]],
        2: [["Sol"], ["La", "Fa#", "Re"], ["Mi"]],
        3: [[], ["Fax"], ["Sibb"]],
    },
    "LH": {
        1: [["Re"]],
        2: [["Mi", "La"]],
        3: [["La"]],
    },
}


def load():
    return converter.parse(SCORE_XML, format="musicxml")


def per_measure(score, fn):
    result = {}
    for label, part in zip(("RH", "LH"), score.parts):
        result[label] = {
            m.number: [fn(e) for e in sorted(m.recurse().notes, key=lambda e: e.getOffsetInHierarchy(m))]
            for m in part.getElementsByClass(stream.Measure)
        }
    return result


def content(score):
    return per_measure(score, lambda e: (tuple(p.nameWithOctave for p in e.pitches), e.quarterLength))


class SolfegeLabelsTest(unittest.TestCase):
    def test_labels_follow_annotation_rules(self):
        self.assertEqual(per_measure(load(), note_labels), EXPECTED)

    def test_octave_flag(self):
        labels = per_measure(load(), lambda e: note_labels(e, with_octave=True))
        self.assertEqual(labels["RH"][1][0], ["Fa#4"])
        self.assertEqual(labels["RH"][2][1], ["La4", "Fa#4", "Re4"])
        self.assertEqual(labels["LH"][1][0], ["Re3"])


class AnnotateTest(unittest.TestCase):
    def test_lyrics_survive_musicxml_roundtrip(self):
        score = load()
        original = content(score)
        list(score.parts[0].recurse().notes)[0].addLyric("old lyric")
        annotate(score)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.musicxml"
            score.write("musicxml", fp=str(out))
            reread = converter.parse(str(out))

        def lyric_lines(e):
            return [ly.text for ly in sorted(e.lyrics, key=lambda ly: ly.number)]

        self.assertEqual(per_measure(reread, lyric_lines), EXPECTED)
        self.assertEqual(content(reread), original)


if __name__ == "__main__":
    unittest.main()

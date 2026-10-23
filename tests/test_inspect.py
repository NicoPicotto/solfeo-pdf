"""Tests for the inspector heuristics that flag doubtful measures."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music21 import chord, clef, meter, note, stream, tie  # noqa: E402

from inspect_omr import clef_changes, find_clef_suspects, find_missing_notes, hands  # noqa: E402


def el(spec):
    """'C4/q', 'C4/h~' (tie start), '~C4/q' (tie stop), 'C4+E4/h' (chord)."""
    tie_type = "stop" if spec.startswith("~") else "start" if spec.endswith("~") else None
    pitches, dur = spec.strip("~").split("/")
    ql = {"w": 4, "h": 2, "q": 1, "e": 0.5, "dq": 1.5, "dh": 3}[dur]
    n = chord.Chord(pitches.split("+"), quarterLength=ql) if "+" in pitches else note.Note(pitches, quarterLength=ql)
    if tie_type:
        n.tie = tie.Tie(tie_type)
    return n


def score(rh, lh, rh_clefs=None):
    """rh/lh: one list of specs per measure ([] = silent bar, filled with a
    whole rest). rh_clefs: {measure_index: clef} changes for the right hand."""
    s = stream.Score()
    for specs_by_measure, first_clef in ((rh, clef.TrebleClef()), (lh, clef.BassClef())):
        part = stream.Part()
        for i, specs in enumerate(specs_by_measure):
            m = stream.Measure(number=i + 1)
            if i == 0:
                m.append([first_clef, meter.TimeSignature("4/4")])
            if part is not None and rh_clefs and first_clef.sign == "G" and i in rh_clefs:
                m.append(rh_clefs[i])
            m.append([el(x) for x in specs] or [note.Rest(quarterLength=4)])
            part.append(m)
        s.insert(0, part)
    return s


LH = ["D3/h", "G3/h"]
FULL = ["C5/q", "D5/q", "E5/q", "F5/q"]


def missing(s):
    return [(b, a, extra) for _, b, a, extra in find_missing_notes(hands(s))]


class MissingNotesTest(unittest.TestCase):
    def test_note_lost_in_the_middle(self):
        s = score([FULL, ["C5/q", "D5/h", "F5/q"]], [LH, LH])
        self.assertEqual(missing(s), [(2, 1, 1)])

    def test_note_lost_at_the_start_of_the_measure(self):
        s = score([FULL, ["D5/q", "E5/h", "F5/q"]], [LH, LH])
        self.assertEqual(missing(s), [(2, 1, 1)])

    def test_silent_other_hand_is_no_evidence(self):
        s = score([FULL, ["C5/q", "D5/h", "F5/q"]], [[], []])
        self.assertEqual(missing(s), [])

    def test_repeated_variation_is_not_a_lost_note(self):
        short = ["C5/q", "D5/h", "F5/q"]
        s = score([FULL, short, short], [LH, LH, LH])
        self.assertEqual(missing(s), [])

    def test_tied_note_counts_once(self):
        tied = ["C5/q", "D5/e~", "~D5/dq", "E5/q"]
        plain = ["C5/q", "D5/h", "E5/q"]
        s = score([tied, plain], [LH, LH])
        self.assertEqual(missing(s), [])

    def test_different_first_duration_is_different_music(self):
        s = score([["A4/w"], ["A4/dq", "F#4/e", "G4/q", "B4/q"]], [LH, LH])
        self.assertEqual(missing(s), [])


class ClefTest(unittest.TestCase):
    # lower half of the bass staff: 3+ ledger lines if read in treble clef
    BASS_RANGE = ["C3/q", "D3/q", "E3/q", "F3/q"]

    def test_missed_clef_change_over_several_measures(self):
        s = score([FULL, self.BASS_RANGE, self.BASS_RANGE, FULL], [LH] * 4)
        self.assertEqual([(n, sign) for _, n, sign in find_clef_suspects(hands(s))], [(2, "G"), (3, "G")])

    def test_single_low_measure_is_not_flagged(self):
        s = score([FULL, self.BASS_RANGE, FULL], [LH] * 3)
        self.assertEqual(find_clef_suspects(hands(s)), [])

    def test_two_ledger_lines_are_normal_music(self):
        low = ["A3/q", "B3/q", "A3/q", "B3/q"]
        s = score([FULL, low, low, FULL], [LH] * 4)
        self.assertEqual(find_clef_suspects(hands(s)), [])

    def test_detected_clef_change_is_listed_not_flagged(self):
        s = score([FULL, self.BASS_RANGE, self.BASS_RANGE], [LH] * 3, rh_clefs={1: clef.BassClef()})
        hp = hands(s)
        self.assertEqual([(n, sign) for _, n, sign in clef_changes(hp)], [(2, "F")])
        self.assertEqual(find_clef_suspects(hp), [])


if __name__ == "__main__":
    unittest.main()

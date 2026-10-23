"""Solfege naming shared by the inspector and the annotator."""

from music21 import chord

SOLFEGE = {"C": "Do", "D": "Re", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}
ALTER_SUFFIX = {0: "", 1: "#", -1: "b", 2: "x", -2: "bb"}


def solfege_name(pitch, with_octave=False):
    # Pitch comes straight from MusicXML <step>/<alter>, which already reflects
    # key signature and in-measure accidentals.
    alter = int(pitch.accidental.alter) if pitch.accidental else 0
    name = SOLFEGE[pitch.step] + ALTER_SUFFIX.get(alter, f"?{alter}")
    return f"{name}{pitch.octave}" if with_octave else name


def is_tie_continuation(n):
    return n.tie is not None and n.tie.type in ("stop", "continue")


def note_labels(element, with_octave=False):
    """Names to print for a note or chord, highest first. Tied continuations
    are left out (only the first note of a tie is named). Rests give []."""
    if isinstance(element, chord.Chord):
        notes = sorted(element.notes, key=lambda n: n.pitch.ps, reverse=True)
        return [solfege_name(n.pitch, with_octave) for n in notes if not is_tie_continuation(n)]
    if element.isRest or is_tie_continuation(element):
        return []
    return [solfege_name(element.pitch, with_octave)]

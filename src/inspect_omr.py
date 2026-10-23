"""Inspect a MusicXML score: measure counts per hand, pickup detection, and
solfege names + durations for the first measures.

Usage: python src/inspect_omr.py <score.mxl|.musicxml> [--measures N] [--octave]
"""

import argparse
import sys
from collections import Counter

from music21 import chord, clef, converter, expressions, note, stream

from solfege import is_tie_continuation, solfege_name

DURATION_ES = {
    "breve": "cuadrada",
    "whole": "redonda",
    "half": "blanca",
    "quarter": "negra",
    "eighth": "corchea",
    "16th": "semicorchea",
    "32nd": "fusa",
    "64th": "semifusa",
}


def duration_name(dur):
    name = DURATION_ES.get(dur.type, dur.type)
    if dur.dots == 1:
        name += " con puntillo"
    elif dur.dots > 1:
        name += f" con {dur.dots} puntillos"
    if dur.tuplets:
        name += f" (tresillo)" if dur.tuplets[0].numberNotesActual == 3 else " (grupo irregular)"
    return name


def describe(element, with_octave):
    if isinstance(element, note.Rest):
        return "silencio"
    if isinstance(element, chord.Chord):
        chord_notes = sorted(element.notes, key=lambda n: n.pitch.ps, reverse=True)
        chord_tied = is_tie_continuation(element)
        names = [
            solfege_name(n.pitch, with_octave) + (" (ligada)" if chord_tied or is_tie_continuation(n) else "")
            for n in chord_notes
        ]
        return "acorde " + " / ".join(names)
    name = solfege_name(element.pitch, with_octave)
    return name + (" (ligada, no se nombra)" if is_tie_continuation(element) else "")


def hands(score):
    """Return [(label, part)] — staff 1 = right hand, staff 2 = left hand."""
    parts = list(score.parts)
    labels = ["Mano derecha", "Mano izquierda"]
    return [(labels[i] if i < 2 else f"Pentagrama {i + 1}", p) for i, p in enumerate(parts)]


def pickup_info(part):
    measures = list(part.getElementsByClass(stream.Measure))
    if not measures:
        return False, measures
    first = measures[0]
    ts = first.timeSignature or first.getContextByClass("TimeSignature")
    short = ts is not None and first.duration.quarterLength < ts.barDuration.quarterLength
    return (first.number == 0 or short), measures


def measure_issues(measures):
    issues = []
    for m in measures:
        ts = m.timeSignature or m.getContextByClass("TimeSignature")
        if ts is None:
            continue
        expected = ts.barDuration.quarterLength
        actual = m.duration.quarterLength
        if actual != expected:
            issues.append((m.number, actual, expected))
    return issues


def find_fermatas(hand_parts):
    """OMR often mistakes tuplet brackets for fermatas: flag every one."""
    found = []
    for label, part in hand_parts:
        for m in part.getElementsByClass(stream.Measure):
            for n in m.recurse().notes:
                if any(isinstance(x, expressions.Fermata) for x in n.expressions):
                    found.append((label, m.number))
    return found


def _content(measure):
    """Per sounding note: (pitch classes high→low, quarterLength).
    Octave-agnostic so a passage repeated an octave higher still counts as
    the same music. A tie continuation is merged into the note it continues
    ('A~A' is one A), unless it opens the bar."""
    items = []
    for e in sorted(measure.recurse().notes, key=lambda e: e.getOffsetInHierarchy(measure)):
        pcs = tuple(p.pitchClass for p in sorted(e.pitches, key=lambda p: p.ps, reverse=True))
        notes = e.notes if isinstance(e, chord.Chord) else [e]
        if items and items[-1][0] == pcs and all(is_tie_continuation(n) for n in notes):
            items[-1] = (pcs, items[-1][1] + e.quarterLength)
            continue
        items.append((pcs, e.quarterLength))
    return items


def _align(short, long):
    """Indexes in `long` matching `short` element by element (pitch classes
    only, leftmost greedy), or None if `short` is not a subsequence."""
    idx, j = [], 0
    for pcs, _ in short:
        while j < len(long) and long[j][0] != pcs:
            j += 1
        if j == len(long):
            return None
        idx.append(j)
        j += 1
    return idx


def find_missing_notes(hand_parts, max_extra=3):
    """Flag measure B when another measure A looks like the same music with
    1..max_extra more notes: B's pitches are a subsequence of A's (the lost
    note can be anywhere, also the first one), the other hand is identical
    and NOT silent (two silent bars are no evidence), and the first matched
    note keeps its duration (so a whole-note A is not 'the same' as a bar
    that starts with a dotted-quarter A), and B's version is rare: unique in
    the piece or less frequent than A's. A real variation tends to repeat
    (Piratas 13/29/106/122); an OMR loss is a one-off. Typical OMR symptom:
    a note was dropped and the rhythm 'fixed' so the measure still adds up."""
    if len(hand_parts) != 2:
        return []
    measures = [list(p.getElementsByClass(stream.Measure)) for _, p in hand_parts]
    contents = [[_content(m) for m in ms] for ms in measures]
    both = [(tuple(contents[0][i]), tuple(contents[1][i])) for i in range(len(contents[0]))]
    frequency = Counter(both)
    warnings = []
    for h in (0, 1):
        other = 1 - h
        for b in range(len(contents[h])):
            cb = contents[h][b]
            if not cb or not contents[other][b]:
                continue
            for a in range(len(contents[h])):
                ca = contents[h][a]
                extra = len(ca) - len(cb)
                if a == b or not 0 < extra <= max_extra or contents[other][a] != contents[other][b]:
                    continue
                idx = _align(cb, ca)
                rare = frequency[both[b]] == 1 or frequency[both[b]] < frequency[both[a]]
                if idx is not None and ca[idx[0]][1] == cb[0][1] and rare:
                    warnings.append((hand_parts[h][0], measures[h][b].number, measures[h][a].number, extra))
                    break
    return warnings


# Staff positions, in steps from the middle line (+ = down). Treble middle
# line is B4, bass middle line is D3: 12 diatonic steps apart.
_OTHER_CLEF_SHIFT = {"G": -12, "F": +12}


def clef_changes(hand_parts):
    """[(label, measure number, clef sign)] after the first clef of each hand."""
    changes = []
    for label, part in hand_parts:
        seen_first = False
        for c in part.recurse().getElementsByClass(clef.Clef):
            if seen_first:
                changes.append((label, c.getContextByClass(stream.Measure).number, c.sign))
            seen_first = True
    return changes


def find_clef_suspects(hand_parts, far=10, inside=4, min_run=2):
    """Runs of >= `min_run` consecutive measures whose notes all sit far from
    the staff (>= `far` steps: 3+ ledger lines) but would all fall on the
    staff with the other clef (treble <-> bass): the usual sign of a clef
    change the OMR missed. A single bar, or 2 ledger lines, is normal music.
    Limit: notes in the UPPER half of the other staff only need 2-3 ledger
    lines, which real passages also use (UMI LH 54-55, Piratas RH 46-51), so
    that case is not flagged."""
    suspects = []
    for label, part in hand_parts:
        run = []
        for m in part.getElementsByClass(stream.Measure):
            if not _clef_suspect(m, far, inside):
                if len(run) >= min_run:
                    suspects += run
                run = []
                continue
            run.append((label, m.number, _clef_suspect(m, far, inside)))
        if len(run) >= min_run:
            suspects += run
    return suspects


def _clef_suspect(m, far, inside):
    """Clef sign if the measure looks written in the wrong clef, else None."""
    positions, sign = [], None
    for e in m.recurse().notes:
        c = e.getContextByClass(clef.Clef)
        if c is None or c.sign not in _OTHER_CLEF_SHIFT:
            return None
        sign = c.sign
        positions += [c.lowestLine + 4 - p.diatonicNoteNum for p in e.pitches]
    if not positions:
        return None
    shifted = [p + _OTHER_CLEF_SHIFT[sign] for p in positions]
    if all(abs(p) >= far for p in positions) and all(abs(p) <= inside for p in shifted):
        return sign
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("--measures", type=int, default=4)
    ap.add_argument("--octave", action="store_true")
    args = ap.parse_args()

    score = converter.parse(args.score)
    hand_parts = hands(score)

    print(f"Archivo: {args.score}")
    print(f"Pentagramas/partes: {len(hand_parts)}")
    first_part = hand_parts[0][1]
    ks = first_part.recurse().getElementsByClass("KeySignature").first()
    ts = first_part.recurse().getElementsByClass("TimeSignature").first()
    print(f"Armadura: {ks.asKey() if ks else '?'} ({ks.sharps if ks else '?'} alteraciones)")
    print(f"Compás: {ts.ratioString if ts else '?'}")

    counts = {}
    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        counts[label] = len(measures)
        clef = part.recurse().getElementsByClass("Clef").first()
        nums = [m.number for m in measures]
        print(f"\n{label}: {len(measures)} compases (numeración {nums[0]}..{nums[-1]}), "
              f"clave {clef.sign if clef else '?'}, anacrusa: {'SÍ' if has_pickup else 'no'}")
        issues = measure_issues(measures[1:] if has_pickup else measures)
        for num, actual, expected in issues:
            print(f"  ⚠ compás #{num}: dura {actual} negras, se esperaban {expected}")

    if len(set(counts.values())) > 1:
        print(f"\n⚠ LAS MANOS NO TIENEN LA MISMA CANTIDAD DE COMPASES: {counts}")
    else:
        print(f"\n✓ Ambas manos tienen {next(iter(counts.values()))} compases")

    fermatas = find_fermatas(hand_parts)
    for label, num in fermatas:
        print(f"⚠ Calderón en compás #{num} ({label}): verificar en el original, "
              f"el OMR suele confundir el corchete de un tresillo con un calderón")
    missing = find_missing_notes(hand_parts)
    for label, b, a, extra in missing:
        print(f"⚠ Compás #{b} ({label}) parece igual al #{a} pero con {extra} nota(s) menos: "
              f"posible nota perdida por el OMR")
    if not fermatas and not missing:
        print("✓ Sin calderones ni compases con notas faltantes respecto de compases equivalentes")

    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        print(f"\n===== {label} =====")
        shown = measures[: args.measures + (1 if has_pickup else 0)]
        for idx, m in enumerate(shown):
            visual = "Anacrusa" if (has_pickup and idx == 0) else f"Compás {idx if has_pickup else idx + 1}"
            print(f"\n{visual}  (número interno de Audiveris: {m.number})")
            elements = sorted(m.recurse().notesAndRests, key=lambda e: (e.getOffsetInHierarchy(m), -_top_ps(e)))
            for e in elements:
                voice = e.getContextByClass(stream.Voice)
                vtag = f" [voz {voice.id}]" if voice is not None and len(m.voices) > 1 else ""
                beat = e.getOffsetInHierarchy(m) + 1
                print(f"  tiempo {float(beat):<5g} {describe(e, args.octave):<40} {duration_name(e.duration)}{vtag}")
    return 0


def _top_ps(e):
    if isinstance(e, chord.Chord):
        return max(p.ps for p in e.pitches)
    if isinstance(e, note.Note):
        return e.pitch.ps
    return -1


if __name__ == "__main__":
    sys.exit(main())

"""Add the solfege name of every note as a lyric.

Usage: python src/annotate.py <score.mxl|.musicxml> [-o out.musicxml] [--octave]
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from music21 import converter, stream

from solfege import note_labels


def annotate(score, with_octave=False):
    """Replace all lyrics with solfege names, in place. Chords get one lyric
    line per note, highest note on line 1. Returns {(part_index, measure): named}."""
    named = Counter()
    for part_index, part in enumerate(score.parts):
        for element in part.recurse().notes:
            element.lyrics = []
            labels = note_labels(element, with_octave)
            for line, label in enumerate(labels, start=1):
                element.addLyric(label, lyricNumber=line)
            measure = element.getContextByClass(stream.Measure)
            named[(part_index, measure.number if measure else None)] += len(labels)
    return named


def default_output(path):
    p = Path(path)
    stem = p.name.split(".")[0]
    return str(p.with_name(f"{stem}.solfeo.musicxml"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("-o", "--output")
    ap.add_argument("--octave", action="store_true")
    args = ap.parse_args()

    score = converter.parse(args.score)
    named = annotate(score, args.octave)
    out = args.output or default_output(args.score)
    score.write("musicxml", fp=out)

    per_part = Counter()
    for (part_index, _), n in named.items():
        per_part[part_index] += n
    print(f"Anotado: {out}")
    for part_index, n in sorted(per_part.items()):
        print(f"  parte {part_index + 1}: {n} nombres de nota")
    return 0


if __name__ == "__main__":
    sys.exit(main())

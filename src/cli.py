"""solfeo-pdf: score -> PDF with the solfege name under each note.

  solfeo-pdf partitura.pdf                 # names written onto the original PDF
  solfeo-pdf partitura.pdf --rerender      # redraw the score with MuseScore instead
  solfeo-pdf partitura.corrected.mxl       # MusicXML input: always redrawn
  solfeo-pdf partitura.pdf --octave --out-dir out
"""

import argparse
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from music21 import converter, stream

from annotate import annotate
from overlay import overlay
from inspect_omr import (clef_changes, find_clef_suspects, find_fermatas, find_missing_notes, hands,
                         measure_issues, pickup_info)
from render import render, title_from_filename

AUDIVERIS = "/Applications/Audiveris.app/Contents/MacOS/Audiveris"
MUSICXML_SUFFIXES = (".mxl", ".musicxml", ".xml")


def base_name(path):
    """'Un-Mundo-Ideal.corrected.mxl' -> 'Un-Mundo-Ideal'."""
    return Path(path).name.split(".")[0]


def run_omr(pdf, out_dir):
    """PDF -> MusicXML with Audiveris. Returns (mxl_path, audiveris_log_path)."""
    stem = Path(pdf).stem
    log_path = out_dir / f"{stem}.audiveris.log"
    started = time.time() - 1
    cmd = [AUDIVERIS, "-batch", "-transcribe", "-export", "-output", str(out_dir), "--", str(pdf)]
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    exported = [p for p in out_dir.glob(f"{stem}*.mxl")
                if p.stat().st_mtime >= started and ".solfeo" not in p.name]
    if proc.returncode != 0 or not exported:
        sys.exit(f"Audiveris falló (exit {proc.returncode}); ver {log_path}")
    if len(exported) > 1:
        names = ", ".join(p.name for p in exported)
        sys.exit(f"Audiveris exportó varios movimientos ({names}); todavía no está soportado.")
    return exported[0], log_path


def audiveris_warnings(log_path):
    """WARN/ERROR lines plus measures Audiveris could not fit rhythmically,
    grouped by message."""
    counts = Counter()
    for line in Path(log_path).read_text(errors="replace").splitlines():
        m = re.match(r"(WARN|ERROR)\s+\[(.*?)\]\s+\S+\s+\d+\s+\|\s+(.*)", line)
        if m:
            counts[f"{m.group(1)} {m.group(3)}"] += 1
            continue
        m = re.search(r"\[.*?#(\d+)\].*?(MeasureStack#\d+ no correct rhythm)", line)
        if m:
            counts[f"hoja {m.group(1)}: {m.group(2)} (numeración local de la hoja)"] += 1
    return counts


def print_summary(score):
    """Prints notes per measure and clef changes. Returns (warnings, doubtful):
    warning texts, and the (measure_index, hand) pairs to highlight in the
    PDF: only where a name may be missing or wrong. A short measure (often
    just a lost rest) or a fermata changes no name: terminal only."""
    hand_parts = hands(score)
    hand_of = {label: i for i, (label, _) in enumerate(hand_parts)}
    index_of = [{m.number: i for i, m in enumerate(part.getElementsByClass(stream.Measure))}
                for _, part in hand_parts]
    counts = {}
    print("\nNotas detectadas por compás:")
    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        counts[label] = len(measures)
        print(f"  {label} ({len(measures)} compases{', con anacrusa' if has_pickup else ''}):")
        cells = [f"{m.number}:{sum(len(e.pitches) for e in m.recurse().notes)}" for m in measures]
        for i in range(0, len(cells), 12):
            print("    " + "  ".join(f"{c:<6}" for c in cells[i:i + 12]))
    changes = clef_changes(hand_parts)
    if changes:
        names = {"G": "sol", "F": "fa", "C": "do"}
        print("Cambios de clave: " + ", ".join(f"{label} a {names.get(sign, sign)} en el compás {num}"
                                               for label, num, sign in changes))

    warnings, doubtful = [], []

    def warn(text, label=None, number=None, mark=False):
        warnings.append(text)
        if mark:
            hand = hand_of[label]
            doubtful.append((index_of[hand][number], hand))

    if len(set(counts.values())) > 1:
        warn(f"Las manos no tienen la misma cantidad de compases: {counts}")
    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        for num, actual, expected in measure_issues(measures[1:] if has_pickup else measures):
            warn(f"Compás #{num} ({label}) dura {actual} negras, se esperaban {expected}", label, num)
    for label, num in find_fermatas(hand_parts):
        warn(f"Calderón en compás #{num} ({label}): verificar (puede ser un corchete de tresillo)", label, num)
    for label, b, a, extra in find_missing_notes(hand_parts):
        warn(f"Compás #{b} ({label}) parece igual al #{a} con {extra} nota(s) menos: posible nota perdida",
             label, b, mark=True)
    for label, num, sign in find_clef_suspects(hand_parts):
        warn(f"Compás #{num} ({label}): las notas encajarían mejor en la otra clave, "
             f"¿cambio de clave no detectado?", label, num, mark=True)
    return warnings, sorted(set(doubtful))


def main():
    ap = argparse.ArgumentParser(description="Agrega el nombre en solfeo a cada nota de una partitura.")
    ap.add_argument("input", help="partitura en PDF, o MusicXML (.mxl/.musicxml) para saltear el OMR")
    ap.add_argument("--octave", action="store_true", help="agregar el número de octava (Do4)")
    ap.add_argument("--rerender", action="store_true",
                    help="redibujar la partitura con MuseScore en vez de escribir sobre el PDF original")
    ap.add_argument("--out-dir", help="carpeta de salida (por defecto, la del archivo de entrada)")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.exists():
        sys.exit(f"No existe: {src}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_name(src)
    out_pdf = out_dir / f"{base}.solfeo.pdf"

    omr_log = None
    rerender = args.rerender
    if src.suffix.lower() == ".pdf":
        print(f"1/2 OMR con Audiveris: {src.name} ...")
        musicxml, omr_log = run_omr(src, out_dir)
        omr_project = musicxml.with_suffix(".omr")
    elif src.suffix.lower() in MUSICXML_SUFFIXES:
        print(f"1/2 OMR salteado: la entrada ya es MusicXML ({src.name}); se redibuja con MuseScore")
        musicxml, rerender = src, True
    else:
        sys.exit(f"Formato no soportado: {src.suffix}")
    score = converter.parse(str(musicxml))

    warnings, doubtful = print_summary(score)

    if rerender:
        print("\n2/2 Anotando y redibujando con MuseScore ...")
        annotate(score, args.octave)
        annotated = out_dir / f"{base}.solfeo.musicxml"
        score.write("musicxml", fp=str(annotated))
        pages, note = render(annotated, out_pdf, title_from_filename(src))
        if note:
            print(f"    nota: {note}")
        result = f"{pages} páginas, redibujado"
    else:
        print("\n2/2 Escribiendo los nombres sobre el PDF original ...")
        stats = overlay(src, omr_project, score, out_pdf, args.octave, doubtful)
        result = (f"{stats.named} nombres, {stats.unknown} notas con '?', "
                  f"{stats.squeezed} nombres achicados o encimados, {stats.marked} compases marcados")
        if stats.discarded:
            warnings.append(f"{stats.discarded} nota(s) que Audiveris vio pero descartó: marcadas con '?'")
        if stats.pos_mismatch or stats.unmatched:
            warnings.append(f"{stats.pos_mismatch + stats.unmatched} nota(s) sin emparejar con el MusicXML: marcadas con '?'")

    if omr_log:
        for msg, n in audiveris_warnings(omr_log).items():
            warnings.append(f"Audiveris: {msg}" + (f" (x{n})" if n > 1 else ""))
    print("\nAdvertencias:" if warnings else "\nSin advertencias.")
    for w in warnings:
        print(f"  ⚠ {w}")

    print(f"\nListo: {out_pdf} ({result})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

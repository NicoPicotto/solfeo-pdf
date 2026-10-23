"""solfeo-pdf: score (PDF or MusicXML) -> PDF with solfege names under each note.

  solfeo-pdf partitura.pdf                 # OMR + annotate + render
  solfeo-pdf partitura.corrected.mxl       # skip OMR (e.g. after a manual fix)
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
from inspect_omr import find_fermatas, find_missing_notes, hands, measure_issues, pickup_info
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
    hand_parts = hands(score)
    counts = {}
    print("\nNotas detectadas por compás:")
    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        counts[label] = len(measures)
        print(f"  {label} ({len(measures)} compases{', con anacrusa' if has_pickup else ''}):")
        cells = [f"{m.number}:{sum(len(e.pitches) for e in m.recurse().notes)}" for m in measures]
        for i in range(0, len(cells), 12):
            print("    " + "  ".join(f"{c:<6}" for c in cells[i:i + 12]))

    warnings = []
    if len(set(counts.values())) > 1:
        warnings.append(f"Las manos no tienen la misma cantidad de compases: {counts}")
    for label, part in hand_parts:
        has_pickup, measures = pickup_info(part)
        for num, actual, expected in measure_issues(measures[1:] if has_pickup else measures):
            warnings.append(f"Compás #{num} ({label}) dura {actual} negras, se esperaban {expected}")
    for label, num in find_fermatas(hand_parts):
        warnings.append(f"Calderón en compás #{num} ({label}): verificar (puede ser un corchete de tresillo)")
    for label, b, a, extra in find_missing_notes(hand_parts):
        warnings.append(f"Compás #{b} ({label}) parece igual al #{a} con {extra} nota(s) menos: posible nota perdida")
    return warnings


def main():
    ap = argparse.ArgumentParser(description="Agrega el nombre en solfeo a cada nota de una partitura.")
    ap.add_argument("input", help="partitura en PDF, o MusicXML (.mxl/.musicxml) para saltear el OMR")
    ap.add_argument("--octave", action="store_true", help="agregar el número de octava (Do4)")
    ap.add_argument("--out-dir", help="carpeta de salida (por defecto, la del archivo de entrada)")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.exists():
        sys.exit(f"No existe: {src}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = base_name(src)

    omr_log = None
    if src.suffix.lower() == ".pdf":
        print(f"1/3 OMR con Audiveris: {src.name} ...")
        musicxml, omr_log = run_omr(src, out_dir)
        print(f"    MusicXML: {musicxml}")
    elif src.suffix.lower() in MUSICXML_SUFFIXES:
        print(f"1/3 OMR salteado: la entrada ya es MusicXML ({src.name})")
        musicxml = src
    else:
        sys.exit(f"Formato no soportado: {src.suffix}")

    print("2/3 Anotando nombres en solfeo ...")
    score = converter.parse(str(musicxml))
    named = annotate(score, args.octave)
    annotated = out_dir / f"{base}.solfeo.musicxml"
    score.write("musicxml", fp=str(annotated))
    print(f"    {sum(named.values())} nombres -> {annotated}")

    print("3/3 Render con MuseScore ...")
    out_pdf = out_dir / f"{base}.solfeo.pdf"
    pages, note = render(annotated, out_pdf, title_from_filename(src))
    if note:
        print(f"    nota: {note}")

    warnings = print_summary(score)
    if omr_log:
        for msg, n in audiveris_warnings(omr_log).items():
            warnings.append(f"Audiveris: {msg}" + (f" (x{n})" if n > 1 else ""))
    print("\nAdvertencias:" if warnings else "\nSin advertencias.")
    for w in warnings:
        print(f"  ⚠ {w}")

    print(f"\nListo: {out_pdf} ({pages} páginas)")
    if omr_log:
        print(f"Para corregir el OMR: editá {musicxml.name} en MuseScore, guardalo como copia "
              f"(.corrected.mxl) y corré solfeo-pdf sobre esa copia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

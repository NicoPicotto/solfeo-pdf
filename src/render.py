"""Render an annotated MusicXML to PDF with the MuseScore CLI.

Usage: python src/render.py <annotated.musicxml> -o out.pdf [--title "..."]
"""

import argparse
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

MSCORE = "/Applications/MuseScore 4.app/Contents/MacOS/mscore"

# MuseScore style overrides. Only these keys change; everything else keeps
# MuseScore defaults (and the lyric font size from the MusicXML <defaults>).
STYLE = {
    "lyricsMinDistance": "1",  # sp between adjacent names; default 0.25 lets them touch
}

# MuseScore 4.7.5 sometimes aborts *after* exporting, while shutting down
# (a mutex is used after static destruction): SIGABRT, seen as exit 134 in a
# shell and -6 from subprocess. That + this message + a fresh, valid output
# file means the export itself succeeded.
KNOWN_SHUTDOWN_CRASH = "mutex lock failed"
SIGABRT_CODES = (-6, 134)

LAYOUT_ATTRS = ("default-x", "default-y", "relative-x", "relative-y")


def title_from_filename(path):
    """'Un-Mundo-Ideal.corrected.mxl' -> 'Un Mundo Ideal'."""
    stem = Path(path).name.split(".")[0]
    return re.sub(r"[-_]+", " ", stem).strip()


def prepare_for_render(src, dst, title, rh_dynamics_above=True):
    """Strip OMR layout so MuseScore lays the score out by itself, and set
    the title (no composer). Right-hand dynamics go above the staff: below it
    they sit between the RH names and the LH staff and read as LH dynamics.
    LH dynamics stay below their staff (above it they'd hit the RH names)."""
    tree = ET.parse(src)
    root = tree.getroot()

    for tag in ("work", "movement-number", "movement-title", "credit"):
        for el in root.findall(tag):
            root.remove(el)
    movement_title = ET.Element("movement-title")
    movement_title.text = title
    root.insert(0, movement_title)
    identification = root.find("identification")
    if identification is not None:
        for creator in identification.findall("creator"):
            identification.remove(creator)
    # No instrument name ("Piano") next to each system: it only costs width.
    for score_part in root.iter("score-part"):
        for tag in ("part-name", "part-abbreviation"):
            el = score_part.find(tag)
            if el is not None:
                el.set("print-object", "no")

    for measure in root.iter("measure"):
        measure.attrib.pop("width", None)
        for print_el in measure.findall("print"):  # forced system/page breaks
            measure.remove(print_el)
        if rh_dynamics_above:
            for direction in measure.findall("direction"):
                is_dynamics = direction.find("direction-type/dynamics") is not None
                if is_dynamics and direction.findtext("staff", "1") == "1":
                    direction.set("placement", "above")

    for el in root.iter():
        for attr in LAYOUT_ATTRS:
            el.attrib.pop(attr, None)

    tree.write(dst, encoding="utf-8", xml_declaration=True)


def write_style(path, overrides):
    body = "\n".join(f"    <{k}>{v}</{k}>" for k, v in overrides.items())
    Path(path).write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<museScore version="4.70">\n  <Style>\n{body}\n  </Style>\n</museScore>\n'
    )


def pdf_page_count(path):
    return len(re.findall(rb"/Type\s*/Page(?!s)", Path(path).read_bytes()))


def _valid_output(path, started):
    p = Path(path)
    if not p.exists() or p.stat().st_mtime < started:
        return False
    if p.suffix.lower() == ".pdf":
        data = p.read_bytes()
        return data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:] and pdf_page_count(p) > 0
    return p.stat().st_size > 0


def run_mscore(src, out, style_path=None, extra_args=()):
    """Export `src` to `out` (format from extension). Returns a note string
    when the known shutdown crash was tolerated, else None. Raises on failure.
    For PNG, MuseScore writes one file per page as <stem>-<n>.png."""
    cmd = [MSCORE, *extra_args, "-o", str(out), str(src)]
    if style_path:
        cmd[1:1] = ["-S", str(style_path)]
    started = time.time() - 1
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    out = Path(out)
    check = out if out.suffix.lower() != ".png" else out.with_name(f"{out.stem}-1.png")
    if proc.returncode == 0 and _valid_output(check, started):
        return None
    if proc.returncode in SIGABRT_CODES and KNOWN_SHUTDOWN_CRASH in log and _valid_output(check, started):
        return "MuseScore se cerró con el error conocido de apagado (134); la exportación está completa."
    tail = "\n".join(line for line in log.splitlines() if "mach_o_image" not in line)[-2000:]
    raise RuntimeError(f"MuseScore falló (exit {proc.returncode}) exportando {out}:\n{tail}")


def render(annotated, out_pdf, title, style=STYLE):
    """Clean the MusicXML, then export PDF. Returns (pages, note)."""
    with tempfile.TemporaryDirectory() as tmp:
        prepared = Path(tmp) / "render.musicxml"
        style_path = Path(tmp) / "style.mss"
        prepare_for_render(annotated, prepared, title)
        write_style(style_path, style)
        note = run_mscore(prepared, out_pdf, style_path)
    return pdf_page_count(out_pdf), note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--title")
    args = ap.parse_args()
    pages, note = render(args.score, args.output, args.title or title_from_filename(args.score))
    print(f"PDF: {args.output} ({pages} páginas)")
    if note:
        print(f"  nota: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# solfeo-pdf

Le das una partitura de piano en PDF y te devuelve **la misma partitura con el nombre de cada nota escrito debajo** (Do, Re, Mi, Fa, Sol, La, Si). Está pensado para quien está aprendiendo piano y todavía no lee partituras con soltura: abres el resultado en la tablet o lo imprimes, lo pones en el atril y tocas.

La partitura **no se redibuja**: los nombres se escriben encima del PDF original, así que la música queda exactamente igual que en el archivo que tenías.

```
solfeo-pdf "Para Elisa.pdf"     →     Para Elisa.solfeo.pdf
```

## Qué hace, en detalle

- Escribe el nombre de cada nota debajo de su pentagrama, tanto en la mano derecha como en la izquierda.
- Usa los nombres del solfeo de Do fijo (Do = C, Re = D, Mi = E...), como se enseña en los países de habla hispana.
- Usa la **alteración que realmente suena**: tiene en cuenta la armadura de clave y las alteraciones que siguen vigentes dentro del compás. Por ejemplo, si la armadura tiene un Fa#, todos los Fa se nombran **Fa#**.
- Alteraciones: `#` sostenido, `b` bemol, `x` doble sostenido, `bb` doble bemol (por ejemplo: Fa#, Sib).
- **Acordes:** un nombre por nota, apilados de la más aguda (arriba) a la más grave (abajo).
- **Notas ligadas:** solo se nombra la primera.
- Los silencios se ignoran.
- Opcional: agregar el número de octava (Do4, La3...).

## Antes de usarlo: qué esperar

El programa "lee" la partitura con reconocimiento óptico de música (OMR), igual que un OCR lee texto. Funciona muy bien, pero **no es perfecto**, y por eso te avisa cuando duda:

| En el PDF verás | Qué significa |
|---|---|
| Nombres en **azul** debajo de cada pentagrama | El nombre de cada nota. |
| Nombres en **dos alturas** alternadas | Notas muy juntas (por ejemplo, corcheas seguidas): los nombres se alternan para no pisarse. Se leen de izquierda a derecha, igual que las notas. |
| Un nombre **más pequeño** de lo normal | No había espacio (por ejemplo, junto a un tresillo) y se redujo para que quepa. |
| Un **"?"** | El programa vio una nota ahí, pero no pudo saber cuál es. Búscala en la partitura. |
| Un **recuadro amarillo suave** detrás de un compás | Compás dudoso: puede faltar un nombre o haber uno equivocado. Compáralo con la partitura antes de fiarte de los nombres. |

Una nota que el programa no reconoció **sigue estando en la partitura**, solo que sin nombre: la música nunca se modifica, solo se le agregan nombres. Si un nombre te parece extraño, fíate de la partitura.

Al terminar, la Terminal también muestra un resumen con las advertencias (compases incompletos, cambios de clave, etc.).

**Limitaciones:**

- Solo funciona con **PDFs digitales**: exportados desde un programa de partituras (MuseScore, Finale, Sibelius...) o descargados de sitios de partituras. **No funciona bien con partituras escaneadas o fotografiadas.**
- Por ahora solo funciona en **macOS**.
- Está pensado para **piano** (dos pentagramas: clave de sol y clave de fa).

## Instalación (macOS)

Se hace una sola vez. Hay que usar la Terminal, pero todo es copiar y pegar.

### 1. Homebrew y Python

Si no tienes [Homebrew](https://brew.sh), instálalo siguiendo las instrucciones de su página. Después:

```bash
brew install python git
```

### 2. Audiveris (el programa que "lee" la partitura)

1. Descarga el `.dmg` para tu Mac desde [las versiones publicadas de Audiveris](https://github.com/Audiveris/audiveris/releases): `macosx-arm64` si tu Mac tiene chip Apple (M1, M2, M3...) o `macosx-x86_64` si es Intel. Probado con la versión **5.11.0**.
2. Abre el `.dmg`, acepta la licencia y arrastra **Audiveris** a **Aplicaciones**.
3. Audiveris ya incluye Java: no hace falta instalar nada más.
4. La primera vez, macOS puede bloquearlo porque no viene de la App Store. Ábrelo una vez desde Aplicaciones; si aparece el aviso, ve a **Ajustes del Sistema → Privacidad y seguridad** y pulsa **"Abrir igualmente"**.

### 3. Este programa

```bash
git clone https://github.com/NicoPicotto/solfeo-pdf.git
cd solfeo-pdf
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Para poder escribir `solfeo-pdf` desde cualquier carpeta:

```bash
ln -s "$(pwd)/solfeo-pdf" /opt/homebrew/bin/solfeo-pdf
```

(En Macs Intel, usa `/usr/local/bin` en lugar de `/opt/homebrew/bin`.)

### 4. MuseScore (opcional)

Solo hace falta para el modo `--rerender` (explicado más abajo):

```bash
brew install --cask musescore
```

## Uso

```bash
solfeo-pdf partitura.pdf
```

Genera `partitura.solfeo.pdf` en la misma carpeta. Tarda unos 20 a 30 segundos para una partitura de 2 a 4 páginas.

Opciones:

```bash
solfeo-pdf partitura.pdf --octave         # agrega el número de octava: Do4, La3...
solfeo-pdf partitura.pdf --out-dir salida # guarda todo en la carpeta "salida"
solfeo-pdf partitura.pdf --rerender       # redibuja la partitura en vez de escribir sobre el original
```

Junto al PDF final quedan algunos archivos de trabajo (`.mxl`, `.omr` y un `.audiveris.log`). Puedes borrarlos; solo sirven para investigar un error.

### El modo `--rerender`

En vez de escribir sobre el PDF original, crea una partitura nueva con MuseScore, con los nombres como si fueran la letra de una canción. La ventaja es que el espaciado se adapta a los nombres; la desventaja es que **si el reconocimiento perdió una nota, esa nota desaparece de la música**. Por eso no es el modo por defecto.

En este modo también puedes corregir a mano lo que el programa leyó: abre el `.mxl` en MuseScore, corrígelo, guárdalo como copia (por ejemplo `partitura.corrected.mxl`) y ejecuta:

```bash
solfeo-pdf partitura.corrected.mxl
```

## Una nota sobre las partituras

La mayoría de las partituras tienen derechos de autor. Este repositorio **no incluye ninguna**: usa las tuyas, y no publiques en internet los PDFs que genera el programa si la partitura original no es de uso libre.

## Para quien quiera colaborar

```
src/
  cli.py          el comando solfeo-pdf: une todos los pasos
  solfege.py      cómo se nombra cada nota (alteraciones, ligaduras, acordes)
  overlay.py      escribe los nombres sobre el PDF original usando las posiciones que guarda Audiveris
  inspect_omr.py  detecta compases dudosos (notas perdidas, claves sospechosas, compases incompletos)
  annotate.py     modo --rerender: agrega los nombres como letra al MusicXML
  render.py       modo --rerender: dibuja el PDF con MuseScore
tests/
```

Tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

Cómo funciona por dentro: [Audiveris](https://github.com/Audiveris/audiveris) reconoce la partitura y produce dos cosas: un MusicXML (qué nota es cada una) y su proyecto `.omr` (dónde está dibujada cada cabeza de nota en la página). El programa empareja las dos, calcula el nombre con [music21](https://github.com/cuthbertLab/music21) y lo escribe en el PDF con [PyMuPDF](https://github.com/pymupdf/PyMuPDF), esquivando la tinta original para no tapar nada.

## Licencia

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Puedes usar, modificar y compartir el programa libremente; si distribuyes una versión modificada, o la ofreces como servicio en internet, tienes que publicar su código bajo la misma licencia.

Dependencias: Audiveris (AGPL-3.0), PyMuPDF (AGPL-3.0), music21 (BSD-3-Clause), Pillow (MIT-CMU) y MuseScore (GPL-3.0, opcional).

# MixPrep

Web local para preparar canciones para pinchar. Subes una canción y obtienes:

- **LiveMashup**: intro instrumental de 8 compases (o 4/16/32), la voz entra en el compás 9 y acaba en acapella desde el estribillo.
- **Extended**: intro de 8 compases con batería sintética que cambia cada 4, la canción entera y final acapella, outro u original.
- **Acapella** e **instrumental** (separados con IA, Demucs `htdemucs`).

Todo sale en MP3 320 cuadrado a la rejilla, con BPM y tonalidad (Camelot) en el nombre y en las etiquetas ID3.

## Cómo analiza

| Qué | Cómo |
|---|---|
| BPM | Envolvente de onsets → tempo inicial → búsqueda de peine fina (±3 %, paso 0,005 BPM) |
| Rejilla | Tempo fijo + fase. La fase se decide con más peso en graves (bombo) y se afina por debajo de un frame |
| Compás 1 | De los 4 beats posibles elige el que más graves, onsets y cambio armónico tiene |
| Tonalidad | Krumhansl-Schmuckler sobre cromagrama CQT con corrección de afinación; Camelot incluido |
| Entrada de voz | Energía de la pista de voz sostenida; se asigna al compás más cercano (anacrusis al siguiente) |
| Estructura | Segmentación por compases con chroma + MFCC y agrupación por similitud (estribillo = grupo repetido más fuerte) |

Todo se puede corregir a mano en el estudio: BPM (½, ×2, valor exacto), 3/4 o 4/4, dónde cae el 1 (cursor, ±5/±20 ms, ±1 tiempo) y la tonalidad (alternativas). La rejilla se rehace al instante y el metrónomo te deja comprobarla de oído.

## Instalar y arrancar

Necesita Python 3.10+ y [ffmpeg](https://ffmpeg.org) en el PATH (con `rubberband` para cambiar tono/tempo al exportar).

```bash
pip install -r requirements.txt
python server.py
```

Abre http://127.0.0.1:8765. Sin `demucs` instalado usa una separación básica sin IA (peor calidad). Con GPU NVIDIA y PyTorch con CUDA, la separación es mucho más rápida.

## Pruebas

```bash
python tests/make_test_song.py   # canción sintética con stems
python tests/e2e.py              # sube, analiza y exporta contra el servidor en marcha
```

## Límites conocidos

- La rejilla es de tempo fijo: canciones con tempo variable necesitan ajuste manual.
- La estructura (estribillo, verso) es una estimación sin letra; la versión original usa letras de Genius para afinarla y aquí no está.
- El «1» puede fallar en música sin bombo marcado; hay botones para moverlo.
- La batería del Extended es sintética (house, dembow, hip-hop), no samples.

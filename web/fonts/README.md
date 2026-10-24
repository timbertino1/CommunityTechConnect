# Fonts

Self-hosted, SIL Open Font License 1.1 (the `OFL-*.txt` files; none declares a Reserved Font
Name, so trimmed copies keep their names). The sources are the Latin subsets from Fontsource 5.3.0
(T150, research R15). Each was trimmed on 2026-10-24 (T138, `docs/reviews/performance.md`) to what
`web/css/site.css` uses, with the same characters as before:

| File | Weights | Before | After |
|---|---|--:|--:|
| `inter-latin-wght.woff2` | variable, 400-700 | 48,256 B | 32,028 B |
| `archivo-latin-wght.woff2` | variable, 500-800 | 34,928 B | 30,080 B |
| `jetbrains-mono-latin-500.woff2` | 500 (static, hinting removed) | 21,832 B | 20,220 B |

Kept layout features: `ccmp locl calt liga kern mark mkmk rvrn tnum` (`tnum` for the
`tabular-nums` dates and times). Dropped: `frac numr dnom pnum`, which the site doesn't use.

**Checked:** the same characters as before. At every weight the site uses, glyph points move by
less than 1 font unit and advance widths by at most 1 (Inter has 2048 units per em, Archivo
1000), which is under 0.07 px at the largest heading. JetBrains Mono renders the same, apart from
31 pixels off by at most 17/255.

If `site.css` starts using a weight outside these ranges (say Inter 800), retrim from the
Fontsource originals, or the browser will fake the weight.

## How they were made

With fonttools 4.66.1 (`uvx --from "fonttools[woff]==4.66.1" python trim.py`), starting from the
Fontsource files:

```python
import io
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FEATURES = ["ccmp", "locl", "calt", "liga", "kern", "mark", "mkmk", "rvrn", "tnum"]

def trim(src, dst, wght=None, hinting=True):
    font = TTFont(src)
    opts = subset.Options()
    opts.layout_features = FEATURES
    opts.hinting = hinting
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    subsetter = subset.Subsetter(opts)
    subsetter.populate(unicodes=font.getBestCmap().keys())  # keep every character
    subsetter.subset(font)
    if wght:  # narrow the weight axis (after subsetting: fonttools can't subset a fresh instance)
        buf = io.BytesIO()
        font.flavor = None
        font.save(buf)
        buf.seek(0)
        font = instancer.instantiateVariableFont(TTFont(buf), {"wght": wght}, updateFontNames=False)
    font.flavor = "woff2"
    font.save(dst)

trim("inter-latin-wght.woff2", "out/inter-latin-wght.woff2", (400, 700))
trim("archivo-latin-wght.woff2", "out/archivo-latin-wght.woff2", (500, 800))
trim("jetbrains-mono-latin-500.woff2", "out/jetbrains-mono-latin-500.woff2", hinting=False)
```

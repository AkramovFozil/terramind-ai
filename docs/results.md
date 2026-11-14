# Results — 14 November 2026

First full run on real NASA data: MOLA 463 m for Mars, SRTM GL1 for Earth. Window: 25 × 25 km, common 463 m grid. Every enabled site was reviewed and approved **before** the matrix was computed, and every cell is shown.

![Similarity matrix](results/matrix.png)

## Overall similarity (0 = no overlap, 1 = identical)

| Earth site | Role | vs Gale — A | vs Gale — B | vs Meridiani — A | vs Meridiani — B |
|---|---|---|---|---|---|
| Ustyurt Plateau | candidate | **0.12** | 0.12 | **0.74** | 0.71 |
| Yungay, Atacama | known analog | **0.77** | 0.76 | 0.23 | 0.23 |
| MDRS, Utah | known analog | **0.66** | 0.66 | 0.28 | 0.27 |

Weight set A: slope 0.40, relief 0.35, roughness 0.25. Weight set B: equal.

### Per metric

| Pair | Slope | Relief | Roughness (TRI) |
|---|---|---|---|
| Gale – Ustyurt | 0.14 | 0.10 | 0.12 |
| Gale – Yungay | 0.75 | 0.84 | 0.70 |
| Gale – MDRS | 0.81 | 0.47 | 0.71 |
| Meridiani – Ustyurt | 0.87 | 0.75 | 0.51 |
| Meridiani – Yungay | 0.26 | 0.21 | 0.21 |
| Meridiani – MDRS | 0.20 | 0.51 | 0.10 |

Histograms for each pair: [results/pairs/](results/pairs/). Quick-looks and window parameters (`roi.json`, with approval time and parameter hash) for each site: [results/sites/](results/sites/).

## What this shows

1. **The method recognises known analogs.** Yungay and MDRS, both established Mars analog sites, score 0.77 and 0.66 against the Gale crater floor.
2. **Ustyurt is not a Gale-type analog at this scale** (0.12). Its plateau surface is far smoother: median slope 0.1° vs 1.4° at Gale, roughness 0.8 m vs 9 m.
3. **Ustyurt is a Meridiani-type analog** (0.74), at the same level as the known analogs reach against Gale. The pattern is reversed for the validation sites (0.23 and 0.28 against Meridiani).
4. **The ranking does not depend on the weights.** Spearman ρ between the A and B rankings is 1.0 for both references. With only three Earth sites this is a weak test.

## Limits — read before quoting a number

- **Meridiani was added after the first score.** Gale vs Ustyurt (0.12) came first; Meridiani was then added as a second reference because Ustyurt looked much flatter than Gale's floor. This is logged in [methodology.md](methodology.md#decision-log). Yungay and MDRS were planned from the start.
- **A high Meridiani score mostly means "equally flat".** Any very flat plain may score high against Meridiani. We have not yet tested a flat Earth site that is *not* a Mars analog (a negative control), so the specificity of the Meridiani match is unknown.
- **Shape only.** The scores compare slope, relief and roughness distributions at 463 m. They say nothing about rock type, minerals, climate or habitability.
- **One 25 km window per site.** Another window in the same region can give a different score.
- **MOLA near the equator is partly interpolated** between orbit tracks, which smooths both Mars references (Gale at 4.5° S, Meridiani at 1.9° S).

## Reproduce

```bash
python -m terramind prepare --site <id>   # for gale, meridiani, ustyurt, yungay, mdrs
python -m terramind approve --site <id>   # after looking at the quick-look
python -m terramind matrix
```

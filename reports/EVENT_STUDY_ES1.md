# ES-1 — do verified filing events predict anything?

_Run 2026-09-12 11:17 UTC. Registered in [PREREGISTRATION_EVENT_STUDY.md](PREREGISTRATION_EVENT_STUDY.md) before any return was computed._

> **This is not evidence.** All 15 corpus names are in today's basket or holdings, selected because they are here now. Survivorship on the live universe is worth ~3.8 points a year — more than the effect being looked for — and it biases *toward* making names look good after bad news, because the ones that never recovered are not in the sample. A clean answer needs a point-in-time universe, which is open-work item 1 and still an empty list.

`AR` is log return of the name minus log return of the equal-weight corpus over the same days. `t0` is the first trading day the filing was actionable: after a 15:30 IST dissemination, that is the next day.

### PRIMARY — high materiality, veto-shaped (what AI-V2 acts on)

**61 name-days · 14 names · 2757 underlying events**

| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |
|---|---:|---:|---:|---:|
| 5d | +0.68% | +1.49 | 14 | +0.88 (mean +0.66%) |
| 20d | -0.62% | -0.77 | 14 | -0.22 (mean -0.34%) |
| 60d | -3.61% | -1.22 | 13 | -0.04 (mean -0.09%) |

**Read the two t columns together.** The pooled column treats every name-day as independent; the per-name column averages within a name first and then tests across the names. Where they disagree, the per-name column is the one to believe — the gap between them IS the clustering, and on the 60-day horizon it is the whole of the effect.

### All high materiality

**103 name-days · 15 names · 3036 underlying events**

| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |
|---|---:|---:|---:|---:|
| 5d | +0.84% | +1.97 | 15 | +0.51 (mean +0.26%) |
| 20d | +0.10% | +0.07 | 15 | +0.53 (mean +0.58%) |
| 60d | -2.47% | -0.69 | 15 | -0.27 (mean -0.58%) |

### Medium materiality

**295 name-days · 15 names · 1065 underlying events**

| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |
|---|---:|---:|---:|---:|
| 5d | +0.11% | +0.48 | 15 | +0.74 (mean +0.25%) |
| 20d | -0.69% | -0.76 | 15 | -0.87 (mean -0.57%) |
| 60d | -1.59% | -0.70 | 15 | +0.12 (mean +0.26%) |

### Low materiality

**65 name-days · 15 names · 122 underlying events**

| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |
|---|---:|---:|---:|---:|
| 5d | -0.09% | -0.26 | 15 | -0.14 (mean -0.07%) |
| 20d | -0.90% | -0.88 | 15 | -1.84 (mean -2.24%) |
| 60d | +0.09% | +0.03 | 15 | -1.12 (mean -2.59%) |

### Every event day (the unconditional base rate)

**463 name-days · 15 names · 4223 underlying events**

| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |
|---|---:|---:|---:|---:|
| 5d | +0.24% | +1.10 | 15 | +0.79 (mean +0.21%) |
| 20d | -0.54% | -0.64 | 15 | -0.50 (mean -0.30%) |
| 60d | -1.53% | -0.62 | 15 | -0.18 (mean -0.33%) |


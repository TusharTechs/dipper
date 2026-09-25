# Dipper engine · model card (v0.1.0)

**What it does.** For one pollution case on one stream reach, Dipper keeps a joint probability over
*what* the pollution is and *where* it enters. It then ranks the next check by value of information.
Every parameter lives in `src/dipper_engine/model.py` (`ModelParams`).

**What it does not do.**
- Diagnose disease or confirm pathogens.
- Predict illness.
- Let a model's reading of a photo override a person. Photo features are a separate, down-weighted observer.
- Replace the person who approves advisories and utility handoffs.

## State space

| Hypothesis | Point source? | Justifies an advisory? |
|---|---|---|
| foul: misconnection or leaking sewer | yes | yes |
| overflow: wet-weather sewer overflow | yes | yes |
| chemical: chemical or detergent discharge | yes | yes |
| sediment: runoff | no | no |
| bloom: algal bloom | no | no (a separate cyanobacteria pack is planned) |
| benign: natural foam, iron bacteria and similar | no | no |

Point-source hypotheses have one state per candidate outfall, plus `OUTSIDE` (upstream of the mapped
reach, or an unmapped entry).

## Likelihood model

| Evidence | Model | Source or rationale |
|---|---|---|
| Look and smell at the stream (and citizen reports) | P(pos) = pres·det + (1 − pres·det)·fa; det = role sensitivity × visibility(h) | US illicit-discharge screening uses colour, odour, turbidity and sheen as indicators (EPA IDDE factsheet). Role sensitivity and false-alarm rates are expert starting values, with trained volunteers set above new ones. |
| Report features (grey, odour, foam, …) | Mixture: true sighting uses P(f\|h); false alarm uses base rates. Tempered by role trust. | Outfall Safari visual indicators and IDDE indicator tables. Values are expert-set. |
| Photo features (`photo_model` observer) | Same as a look, with sensitivity 0.60, false alarm 0.15 and feature trust 0.4, lower than any person. A feature counts when confidence is ≥ 0.6. It is tempered with nearby reports, since it shows the same scene. | A weak, correlated observer by design. Not yet evaluated on labelled outfall photos. |
| Outfall look | Positive if the outfall is the active source, or if a background outfall is dirty (6%) | Outfall Safari experience that many outfalls show some pollution |
| Ammonium strip | P(high \| foul present) = 0.85; false positive 0.08 | Ammonium tracked faecal indicators and a human DNA marker (R² 0.49–0.88) in Dublin's Elm Park stream (IJERPH 2021) |
| Lab E. coli | Sensitivity 0.95 for sewage; false positive 0.05; 24 h delay | Standard culture methods; the delay reflects typical turnaround |
| Presence | Point source: discharging with activity(h, time), and upstream of the check. Diffuse: fixed visibility rate. | Misconnections are intermittent (washing machines are the most common culprit, per Water UK) |
| Persistence | For 2 h after a positive sighting, activity ≥ 0.85 | Discharges come in bursts. Without this, clean checks right after reports would be under-weighted. |

## Priors

| Parameter | Dry (rain in 48 h under 5 mm) | Wet |
|---|---|---|
| foul | 0.35 | 0.20 |
| overflow | 0.03 | 0.30 |
| chemical | 0.12 | 0.08 |
| sediment | 0.08 | 0.25 |
| bloom | 0.12 (×2 if max temperature ≥ 28 °C) | 0.05 |
| benign | 0.30 | 0.12 |

Without weather data, the dry and wet priors are averaged. Candidate outfalls start with equal
weight. `OUTSIDE` gets 10% of the point-source mass. In production, the OAH distance-to-sewage-station
and faecal-risk scores should set the candidate weights.

## Safeguards against overconfidence

- **Correlated reports.** The k-th report within 150 m of earlier reports enters with exponent 1/(1 + 0.5k).
- **Outlier model.** With probability 0.08, an observation is treated as uninformative. This bounds any
  single likelihood ratio.
- **Stopping.** Localization is proposed at 0.85. A person decides, and the utility's dye test or CCTV confirms.

## Decision model

For the advisory decision, the losses are: a false advisory costs 1; a missed advisory costs 4 × exposure
stakes (0..1, from contact places near the reach). The score is:

    score = EVSI(advisory) + 1.2 · expected source-entropy reduction (bits) − cost − 0.1 · delay_days

Relative costs:

| Check | Cost |
|---|---|
| Citizen look | 0.05 |
| Photo features (`photo_model` observer) | Same as a look, with sensitivity 0.60, false alarm 0.15 and feature trust 0.4, lower than any person. A feature counts when confidence is ≥ 0.6. It is tempered with nearby reports, since it shows the same scene. | A weak, correlated observer by design. Not yet evaluated on labelled outfall photos. |
| Outfall look | 0.06 |
| Ammonium strip | 0.12 |
| Lab sample | 0.50 |

The search weight (1.2) was chosen on SourceBench as the best trade-off between success rate and cost
(sweep: 0.6, 1.2, 2.0, 3.0).

## Known limitations

- Every likelihood is a literature or expert starting value, with no local calibration yet.
  The plan: expert review by OAH ecologists, then recalibration from lab outcomes (Dawid–Skene).
- Only one active source is modelled. Multiple simultaneous sources are approximated through `OUTSIDE`
  and the outlier model.
- Travel time uses a fixed velocity (0.2 m/s dry, 0.5 m/s wet), not hydraulics.
- Exposure is proximity-based. It is not a dose–response model.
- **SourceBench is a simulation.** The simulated world differs from the model in two ways: it is noisier
  (`--misspec`), and its discharges come in bursts. Real performance is unknown until piloted.

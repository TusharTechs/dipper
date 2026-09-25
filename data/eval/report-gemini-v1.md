# Photo feature evaluation · gemini (gemini-flash-latest)

35 Wikimedia Commons photos (openly licensed; sources in `candidates.json`), labelled by the developer from each photo and its Commons description. **Not expert-verified; small sample.** Every photo went through `redact()` first, exactly as in production. A feature counts as present at confidence ≥ 0.6.

## Image level

- Polluted photos that produced a positive observation: **93% (14/15)**
- Clean photos that produced a false alarm: **40% (4/10)**
- Out-of-scope images (satellite, no water) correctly kept out of the evidence: **100% (7/7)**
- In-scope photos admitted as evidence: **100% (28/28)**
- Median model latency: 4.86 s · errors: 0

## Per feature (in-scope photos, ambiguous labels excluded)

| Feature | Recall | Precision | False positives on negatives |
|---|---|---|---|
| grey | 0% (0/1) | 0% (0/1) | 4% (1/24) |
| sewage_fungus | 100% (2/2) | 100% (2/2) | 0% (0/26) |
| foam | 80% (4/5) | 80% (4/5) | 5% (1/22) |
| brown_turbid | 100% (2/2) | 22% (2/9) | 29% (7/24) |
| green | 100% (2/2) | 100% (2/2) | 0% (0/24) |
| pipe_flowing | 100% (1/1) | 100% (1/1) | 0% (0/25) |
| dead_fish | 100% (3/3) | 100% (3/3) | 0% (0/25) |

## Disagreements

- foam-01: foam expected True, got False (conf 0.70) - Shimna River, foam at rapids (Commons: foam pollution)
- green-03: brown_turbid expected False, got True (conf 0.96) - Aerial photo, algae in bay (Commons description; colour cast)
- outfall-01: brown_turbid expected False, got True (conf 0.65) - Shoreline at wet-weather discharge sign, no visible discharge
- outfall-02: brown_turbid expected False, got True (conf 0.85) - Shoreline at discharge point, no visible discharge
- outfall-03: brown_turbid expected False, got True (conf 0.65) - Shoreline at discharge sign, no visible discharge
- outfall-08: grey expected True, got False (conf 0.30) - Untreated sewage plume in Moose River (colour cast)
- outfall-08: foam expected False, got True (conf 0.65) - Untreated sewage plume in Moose River (colour cast)
- outfall-08: brown_turbid expected False, got True (conf 0.90) - Untreated sewage plume in Moose River (colour cast)
- outfall-09: brown_turbid expected False, got True (conf 0.95) - Industrial effluent pouring into river
- grey-04: grey expected False, got True (conf 0.60) - River choked with litter; litter is not a sewage feature
- grey-08: brown_turbid expected False, got True (conf 0.75) - Sphaerotilus natans (sewage fungus) under water

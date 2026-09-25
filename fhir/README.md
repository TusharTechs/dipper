# FHIR: Dipper response profiles on top of the OneAquaHealth IG

The OneAquaHealth IG (`hl7.eu.fhir.oah`, R4, [hl7-eu/oah](https://github.com/hl7-eu/oah)) models measurements.
Dipper adds the response side as a small FSH IG in `ig/` that depends on it.

| Profile | Base | Rules |
|---|---|---|
| DipperCitizenObservation | Observation | `status` may be preliminary; subject LocationOah; code uses OAH `#foam` ("Foam/colour/smell"), `#ammonium` or `#coliforms` alongside a Dipper code |
| DipperSourceCase | DetectedIssue | fixed code `suspected-point-source`; implicated outfall and reach; evidence → Observations |
| DipperExposureRisk | RiskAssessment | subject GroupOah (people and animals using the reach); decimal probability; rationale required |
| DipperSiteFlag | Flag | subject LocationOah; period required |
| DipperCheckRequest | ServiceRequest | check type from `dipper-check-types`; value-of-information and cost extensions; subject LocationOah |
| DipperFieldTask | Task | basedOn ServiceRequest; `for` LocationOah |
| DipperAdvisory | Communication | subject GroupOah; about Flag and RiskAssessment; sender (human approver) required |
| DipperEngineProvenance | Provenance | agent Device (engine version); entity → source observations |

Synthetic content carries `meta.tag` data tier `simulated`, `meta.security` HL7 ActReason `HTEST`, and ids prefixed `SIM-`.

## Validate

```bash
uv run python scripts/export_fhir_examples.py   # writes examples/c014-searching and c014-handed-off bundles
./fhir/validate.sh                              # builds OAH + Dipper with SUSHI, runs the HL7 validator
```

Result on 25 Sep 2026 (validator_cli latest, `-tx n/a`):
- **0 errors** in both bundles.
- **1 warning** in each: the `reach-users` cohort characteristic is not in OAH's extensible cohort value set,
  which covers age and sex only. This is a proposed addition upstream.
- Terminology-server checks were disabled for speed, so the SNOMED codes were not verified against a
  terminology server.

## Suggested upstream issues for hl7-eu/oah

These are public actions, so file them yourself if you want to:

1. A citizen or preliminary Observation profile. `ObservationIndicatorsOah` fixes `status = final`.
2. Response-side profiles along the lines of this folder.
3. `pH` units should be UCUM `[pH]`.
4. Air-quality codes use an undefined code system rather than the OAH CodeSystem.
5. A cohort characteristic for users of a place (not only residents).

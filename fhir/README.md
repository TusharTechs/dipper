# fhir (to build)

Dipper response profiles (FSH), depending on the OneAquaHealth IG `hl7.eu.fhir.oah` (R4). Build the OAH
IG from source: `git clone https://github.com/hl7-eu/oah && cd oah && sushi .`

| Profile | Base | Purpose |
|---|---|---|
| DipperCitizenObservation | Observation | status preliminary or final; subject LocationOah; derivedFrom Media |
| DipperSourceCase | DetectedIssue | implicated → LocationOah and evidence Observations |
| DipperExposureRisk | RiskAssessment | subject GroupOah (people and dogs using the reach); basis → evidence |
| DipperSiteFlag | Flag | subject LocationOah (active site alert) |
| DipperCheckRequest | ServiceRequest | subject LocationOah; value and cost extensions |
| DipperFieldTask | Task | basedOn ServiceRequest (mission lifecycle) |
| DipperAdvisory | Communication | subject GroupOah; about → Flag and RiskAssessment |
| DipperEngineProvenance | Provenance | agent Device (engine version); entity → inputs |

Synthetic resources carry `meta.security` = HL7 ActReason `HTEST` and ids prefixed `SIM-`.
Validate with: `java -jar validator_cli.jar -version 4.0.1 -ig <oah package> -ig <dipper package> bundle.json`

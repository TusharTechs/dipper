Extension: DipperValueOfInformation
Id: dipper-value-of-information
Title: "Value of information"
Description: "Engine score for a requested check: EVSI for the advisory decision plus search value, minus cost and delay."
Context: ServiceRequest
* value[x] only decimal

Extension: DipperCheckCost
Id: dipper-check-cost
Title: "Check cost"
Description: "Relative effort of a check in normalised units (a citizen look is about 0.05, a lab sample 0.5)."
Context: ServiceRequest
* value[x] only decimal

Profile: DipperCitizenObservation
Parent: Observation
Id: dipper-citizen-observation
Title: "Dipper citizen or field observation"
Description: "A citizen report or field check at a stream point. Unlike ObservationIndicatorsOah, status may be preliminary, because unverified reports are evidence, not results. A verified finding can be promoted to an ObservationIndicatorsOah that cites this one in derivedFrom."
* status from http://hl7.org/fhir/ValueSet/observation-status (required)
* code 1..1
* subject 1..1
* subject only Reference($LocationOah)
* effective[x] 1..1
* effective[x] only dateTime
* derivedFrom only Reference(Media)
* component.code 1..1

Profile: DipperSourceCase
Parent: DetectedIssue
Id: dipper-source-case
Title: "Dipper source case"
Description: "A suspected point source of pollution on a stream reach, with the evidence behind it."
* code 1..1
* code = DipperCodes#suspected-point-source
* implicated 1..*
* evidence 1..*
* evidence.detail 1..*

Profile: DipperExposureRisk
Parent: RiskAssessment
Id: dipper-exposure-risk
Title: "Dipper exposure risk"
Description: "Environmental exposure estimate for the people and animals using a reach. Not a diagnosis and not a disease-risk prediction."
* subject only Reference($GroupOah)
* basis 1..*
* prediction 1..*
* prediction.outcome 1..1
* prediction.probability[x] only decimal
* prediction.rationale 1..1

Profile: DipperSiteFlag
Parent: Flag
Id: dipper-site-flag
Title: "Dipper site flag"
Description: "An active alert at a stream location."
* subject only Reference($LocationOah)
* period 1..1

Profile: DipperCheckRequest
Parent: ServiceRequest
Id: dipper-check-request
Title: "Dipper check request"
Description: "A recommended next check at a stream point or outfall, with its value of information and cost."
* extension contains DipperValueOfInformation named valueOfInformation 1..1 and DipperCheckCost named cost 1..1
* code 1..1
* code from DipperCheckTypes (required)
* subject only Reference($LocationOah)
* supportingInfo 1..*

Profile: DipperConfirmationRequest
Parent: ServiceRequest
Id: dipper-confirmation-request
Title: "Dipper confirmation request"
Description: "Before any repair, the utility confirms the localized entry point with a dye test, smoke test or CCTV. The localization is a probability, never proof."
* code 1..1
* code = DipperCodes#confirm-entry
* subject only Reference($LocationOah)
* reasonCode 1..*
* supportingInfo 1..*

Profile: DipperFieldTask
Parent: Task
Id: dipper-field-task
Title: "Dipper field task"
Description: "The mission that carries out a check or confirmation request."
* basedOn 1..1
* basedOn only Reference(ServiceRequest)
* for 1..1
* for only Reference($LocationOah)

Profile: DipperAdvisory
Parent: Communication
Id: dipper-advisory
Title: "Dipper contact advisory"
Description: "A public contact advisory approved by a named person. A public message, not a health record."
* subject 1..1
* subject only Reference($GroupOah)
* about 1..*
* sender 1..1
* payload 1..*

Profile: DipperEngineProvenance
Parent: Provenance
Id: dipper-engine-provenance
Title: "Dipper engine provenance"
Description: "Records which engine version produced which outputs from which inputs."
* agent 1..*
* agent.who only Reference(Device)
* entity 1..*

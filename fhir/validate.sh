#!/usr/bin/env bash
# Build the OAH IG and the Dipper profiles, then validate the example bundles with the official HL7 validator.
# Requires Java 17+ and Node (for SUSHI). First run downloads the OAH source and validator_cli.jar (~150 MB).
set -euo pipefail
cd "$(dirname "$0")"
# Pinned so the result is reproducible: the OAH IG source commit and the HL7 validator release it was checked with.
OAH_COMMIT=b907cf0869b59d82d9138b3d147fca66f333d911
VALIDATOR_VERSION=6.10.4
mkdir -p .build
if [ ! -d .build/oah ]; then
  git init -q .build/oah && git -C .build/oah remote add origin https://github.com/hl7-eu/oah
  git -C .build/oah fetch -q --depth 1 origin "$OAH_COMMIT" && git -C .build/oah checkout -q FETCH_HEAD
fi
[ -d .build/oah/fsh-generated ] || (cd .build/oah && npx -y fsh-sushi@3 . > /dev/null)
PKG="$HOME/.fhir/packages/hl7.eu.fhir.oah#0.1.0-ci-build/package"
mkdir -p "$PKG" && cp .build/oah/fsh-generated/resources/*.json "$PKG/"
cat > "$PKG/package.json" <<JSON
{"name":"hl7.eu.fhir.oah","version":"0.1.0-ci-build","fhirVersions":["4.0.1"],"canonical":"http://hl7.eu/fhir/ig/oah","dependencies":{"hl7.fhir.r4.core":"4.0.1","hl7.fhir.uv.xver-r5.r4":"0.1.0"}}
JSON
(cd ig && npx -y fsh-sushi@3 . > /dev/null)
[ -f .build/validator_cli.jar ] || curl -fsSL -o .build/validator_cli.jar \
  "https://github.com/hapifhir/org.hl7.fhir.core/releases/download/$VALIDATOR_VERSION/validator_cli.jar"
java -jar .build/validator_cli.jar -version 4.0.1 -tx n/a \
  -ig .build/oah/fsh-generated/resources -ig ig/fsh-generated/resources \
  -output .build/validation.json examples/*.bundle.json > .build/validation.txt
export BUNDLES="$(ls examples/*.bundle.json)"
# Summarise per bundle from the machine-readable result, and fail (for CI) on any error.
node -e '
const r = require("./.build/validation.json"); let bad = 0; const names = process.env.BUNDLES.split("\n")
for (const [k, e] of (r.entry ?? [{ resource: r }]).entries()) {
  const oo = e.resource, n = (s) => oo.issue.filter((i) => i.severity === s).length
  const file = names[k] ?? `bundle ${k + 1}`
  const errors = n("error") + n("fatal"); bad += errors
  console.log(`${errors ? "FAIL" : "ok  "} ${file}: ${errors} errors, ${n("warning")} warnings`)
  for (const i of oo.issue.filter((i) => i.severity !== "information")) console.log(`     ${i.severity}: ${i.details?.text ?? i.diagnostics}`)
}
process.exit(bad ? 1 : 0)'

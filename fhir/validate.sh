#!/usr/bin/env bash
# Build the OAH IG and the Dipper profiles, then validate the example bundles with the official HL7 validator.
# Requires Java 17+ and Node (for SUSHI). First run downloads the OAH source and validator_cli.jar (~150 MB).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .build
[ -d .build/oah ] || git clone -q --depth 1 https://github.com/hl7-eu/oah .build/oah
[ -d .build/oah/fsh-generated ] || (cd .build/oah && npx -y fsh-sushi@3 . > /dev/null)
PKG="$HOME/.fhir/packages/hl7.eu.fhir.oah#0.1.0-ci-build/package"
mkdir -p "$PKG" && cp .build/oah/fsh-generated/resources/*.json "$PKG/"
cat > "$PKG/package.json" <<JSON
{"name":"hl7.eu.fhir.oah","version":"0.1.0-ci-build","fhirVersions":["4.0.1"],"canonical":"http://hl7.eu/fhir/ig/oah","dependencies":{"hl7.fhir.r4.core":"4.0.1","hl7.fhir.uv.xver-r5.r4":"0.1.0"}}
JSON
(cd ig && npx -y fsh-sushi@3 . > /dev/null)
[ -f .build/validator_cli.jar ] || curl -sSL -o .build/validator_cli.jar https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar
java -jar .build/validator_cli.jar -version 4.0.1 -tx n/a \
  -ig .build/oah/fsh-generated/resources -ig ig/fsh-generated/resources \
  -output .build/validation.json examples/*.bundle.json | tee .build/validation.txt | grep -E "^(Success|\*FAILURE\*|  Error|  Warning)|errors,.*warnings" | head -60

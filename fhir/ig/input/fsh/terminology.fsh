CodeSystem: DipperCodes
Id: dipper-codes
Title: "Dipper codes"
Description: "Local codes for citizen pollution signals, check types, case and risk concepts, and data tiers."
* ^caseSensitive = true
* ^experimental = true
* #pollution-sighting "Pollution sighting" "A person reports visible or olfactory signs of pollution in a stream."
* #grey-discolouration "Grey or milky water"
* #sewage-odour "Sewage smell"
* #pipe-dry-weather-flow "Pipe discharging"
* #sewage-fungus "Sewage fungus growth"
* #brown-turbid "Brown, muddy water"
* #green-water "Green water or scum"
* #dead-fish "Dead fish"
* #foam "Foam"
* #instream-look "Look and smell at the stream"
* #outfall-look "Look and smell at an outfall"
* #ammonium-strip "Ammonium test strip"
* #lab-ecoli "Laboratory E. coli sample"
* #above-threshold "Above screening threshold"
* #below-threshold "Below screening threshold"
* #suspected-point-source "Suspected point-source pollution" "Pollution entering a stream at a single point (misconnection, leaking sewer, overflow or discharge)."
* #faecal-contact-exposure "Contact with faecally contaminated water" "Environmental exposure estimate; not a diagnosis."
* #contact-advisory "Avoid contact with the water"
* #reach-users "People and animals using a stream reach"
* #observed "Observed" "Measured or reported."
* #modelled "Modelled" "Reanalysis, forecast or satellite-derived."
* #simulated "Simulated" "Generated for a demonstration or benchmark; not real-world data."

ValueSet: DipperCheckTypes
Id: dipper-check-types
Title: "Dipper check types"
* ^experimental = true
* DipperCodes#instream-look
* DipperCodes#outfall-look
* DipperCodes#ammonium-strip
* DipperCodes#lab-ecoli

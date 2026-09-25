// The demo film, scene by scene. make.mjs reads it for the narration and timing, film.js for the pictures.
//   vo    what the narrator says, also shown as a subtitle. {checks}, {top}, {p} and {narrowed} are read off the
//         live app during capture, so the words always match what the viewer sees.
//   say   the same line spelled for the speech synthesiser, when a word needs help ("FHIR" is said "fire").
//   min   shortest time on screen (s); pad is the pause after the line; xin is the crossfade from the last scene.
//   Live scenes (kind "phone" or "desk") play the capture from their beat to the next one; cam lists camera
//   moves as [seconds into the scene, box name or "full", zoom].
export const VOICE = { name: 'Ava (Premium)', rate: 168 }

export const SCENES = [
  // ---------- the problem ----------
  { id: 'open', kind: 'open', min: 9, lead: 1.4,
    vo: 'Every city has streams like this one. Children play beside them. Dogs swim in them. People walk them every morning.' },
  { id: 'grey', kind: 'grey', min: 8, xin: 0,
    vo: 'Then, on a dry morning, the water turns grey, and it starts to smell. Somewhere upstream, a pipe is carrying sewage straight into the stream.' },
  { id: 'haystack', kind: 'haystack', min: 12, xin: 0,
    vo: 'Finding that pipe is the hard part. A stream has dozens of outfalls, and the discharge comes and goes. So crews walk the bank, one pipe at a time. A pipe that looks clean today can be dirty tomorrow.' },
  { id: 'scale', kind: 'scale', min: 7,
    vo: 'It is not rare. In the UK alone, an estimated 150,000 to 500,000 homes have a misconnected drain.',
    say: 'It is not rare. In the U.K. alone, an estimated one hundred and fifty thousand to half a million homes have a misconnected drain.' },
  { id: 'void', kind: 'void', min: 8,
    vo: 'And the people who notice first, walkers, parents, schools, report into a void. They never hear back, and what they saw never reaches the search.' },
  { id: 'law', kind: 'law', min: 8,
    vo: "Europe's recast Urban Wastewater Directive now requires large cities to plan for exactly this, storm overflows and urban runoff included, by 2033.",
    say: "Europe's recast Urban Wastewater Directive now requires large cities to plan for exactly this, storm overflows and urban runoff included, by twenty thirty-three." },
  { id: 'question', kind: 'question', min: 4.2, pad: 0.9,
    vo: 'What if every report made the search smarter?' },

  // ---------- what we built ----------
  { id: 'logo', kind: 'logo', min: 10, lead: 1.6, xin: 0.9,
    vo: 'This is Dipper. It is named after a small songbird that ecologists treat as a living sign of a healthy stream. Dipper turns citizen reports into a search that finds the polluting pipe.' },
  { id: 'how-evidence', kind: 'how', step: 1, min: 6,
    vo: 'Every report is snapped to a real stream network, built from OpenStreetMap, with flow direction and culverts.' },
  { id: 'how-belief', kind: 'how', step: 2, min: 9, xin: 0.35,
    vo: 'Dipper keeps an exact probability over what the pollution is, and where it enters: six explanations, every candidate outfall, with live weather setting the odds.' },
  { id: 'how-check', kind: 'how', step: 3, min: 9, xin: 0.35,
    vo: 'Then it chooses the next best check: the one that tells us the most, for the least effort. Even a clean result counts. It lowers every source upstream.' },
  { id: 'how-citizen', kind: 'how', step: 4, min: 6, xin: 0.35,
    vo: 'It can even ask the person who reported to make that check: one short mission nearby, in their own language.' },
  { id: 'how-people', kind: 'how', step: 5, min: 10, xin: 0.35,
    vo: 'Once the source is found, people decide. The case goes to the utility as an HL7 FHIR bundle on the OneAquaHealth guide, and a public-health officer approves an advisory that keeps what was observed apart from what was inferred.',
    say: 'Once the source is found, people decide. The case goes to the utility as an H L 7 fire bundle on the One Aqua Health guide, and a public-health officer approves an advisory that keeps what was observed apart from what was inferred.' },
  { id: 'bench', kind: 'bench', min: 9,
    vo: 'In simulation, across seven stream networks, Dipper doubles the success rate of walking the bank, with about half the checks, at lower cost.' },

  // ---------- live ----------
  { id: 'live', kind: 'live', min: 3.6, pad: 0.6,
    vo: 'Here it is, running live.' },
  { id: 'p-open', kind: 'phone', beat: 'p-open', head: 'A walker sees grey water',
    vo: 'A walker notices grey water. They open Dipper in the browser. No account, and no app to install.' },
  { id: 'p-lang', kind: 'phone', beat: 'p-lang', head: 'In their language', xin: 0,
    vo: 'It speaks their language, Portuguese here, or English.' },
  { id: 'p-where', kind: 'phone', beat: 'p-where', head: 'Where they are standing', xin: 0,
    vo: 'They choose the stream and where they are standing,' },
  { id: 'p-signs', kind: 'phone', beat: 'p-signs', head: 'What they see and smell', xin: 0,
    vo: 'and tap what they see and smell.' },
  { id: 'p-send', kind: 'phone', beat: 'p-send', head: 'Under a minute', xin: 0,
    vo: 'Send. It takes under a minute, and it even works offline.' },
  { id: 'p-mission', kind: 'phone', beat: 'p-mission', head: 'A nearby mission', xin: 0,
    vo: 'Instead of silence, they get a thank-you, and one short check nearby that sharpens the search.' },
  { id: 'p-answer', kind: 'phone', beat: 'p-answer', head: 'Clean still counts', xin: 0,
    vo: 'The water there looks clean, and that still counts. It just ruled out {narrowed} of the places the source could be.' },
  { id: 'd-signin', kind: 'desk', beat: 'd-signin', xin: 0.8, cam: [[0, 'full']],
    vo: 'In the operations room, an investigator opens a case.' },
  { id: 'd-replay', kind: 'desk', beat: 'd-replay', xin: 0, cam: [[0, 'demo', 1.35], [2.4, 'full']],
    vo: 'This one replays a real stream in Coimbra, with real weather. Its outfalls and results are simulated.',
    say: 'This one replays a real stream in Kweembra, with real weather. Its outfalls and results are simulated.' },
  { id: 'd-case', kind: 'desk', beat: 'd-case', xin: 0, cam: [[0, 'full'], [0.6, 'head', 1.55], [3.4, 'left', 1.45], [6.4, 'right', 1.5]],
    vo: 'Dipper shows what it probably is, where it probably enters, and the best next checks, each with both outcomes spelled out, before anyone leaves the office.' },
  { id: 'd-search', kind: 'desk', beat: 'd-search', xin: 0, cam: [[0, 'right', 1.5], [1.8, 'map', 1.3]],
    vo: 'Run the top check, and the probability moves along the real stream.' },
  { id: 'd-search2', kind: 'desk', beat: 'd-search2', xin: 0, maxSpeed: 2.2, cam: [[0, 'map', 1.3]],
    vo: 'Every result, clean or polluted, sharpens the picture.' },
  { id: 'd-localized', kind: 'desk', beat: 'd-localized', xin: 0, cam: [[0, 'full'], [0.4, 'head', 1.6], [3.2, 'map', 1.35]],
    vo: '{checks} checks later, the source is localized: outfall {top}, at {p} percent.',
    say: '{checks} checks later, the source is localized: outfall {topSay}, at {p} percent.' },
  { id: 'd-handoff', kind: 'desk', beat: 'd-handoff', xin: 0, cam: [[0, 'full'], [4.2, 'stats', 1.5], [7.5, 'confirm', 1.45]],
    vo: 'One click hands it to the utility: a FHIR bundle with every reference resolved, and a request to confirm the pipe with a dye test before anyone digs.',
    say: 'One click hands it to the utility: a fire bundle with every reference resolved, and a request to confirm the pipe with a dye test before anyone digs.' },
  { id: 'd-ph', kind: 'desk', beat: 'd-ph', xin: 0, maxSpeed: 2, cam: [[0, 'full'], [7.0, 'tiers', 1.3]],
    vo: 'A public-health officer reviews the drafted advisory: what was observed, what is inferred, the possible risk, and what still needs a lab to confirm.' },
  { id: 'd-approve', kind: 'desk', beat: 'd-approve', xin: 0, pad: 0.2, cam: [[0, 'full']],
    vo: 'Approve,' },
  { id: 'd-public', kind: 'desk', beat: 'd-public', xin: 0, maxSpeed: 2, cam: [[0, 'full'], [3.6, 'pubmap', 1.25]],
    vo: 'and it is on the public map, in Portuguese and English, without ever showing a suspected pipe or an address.' },

  // ---------- close ----------
  { id: 'loop', kind: 'loop', min: 8, xin: 0.9,
    vo: 'Report. Case. Next best check. Source. Hand-off. Advisory. Fix verified.' },
  { id: 'pillars', kind: 'pillars', min: 10,
    vo: 'Dipper is built on open data and open standards. It is private by design, accessible, and runs as a single container, ready for any city.' },
  { id: 'end', kind: 'end', min: 8, pad: 3.2, xin: 1,
    vo: 'Dipper. Every report brings the source closer.' },
]

// The benchmark shown on screen (README, SourceBench results, SIMULATION).
export const BENCH = [
  { name: 'Walk the bank', ok: 28, checks: 20, cost: 1.49 },
  { name: 'Bisect the stream', ok: 43, checks: 13, cost: 0.95 },
  { name: 'Dipper', ok: 56, checks: 9.5, cost: 1.30, us: true },
]

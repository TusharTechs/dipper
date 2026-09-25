// Citizen-facing text in English and the languages of the OneAquaHealth pilot cities (Coimbra, Oslo, Ghent).
// Portuguese, Norwegian (Bokmål) and Dutch are draft translations; native speakers should review them before a pilot.

export type Lang = 'en' | 'pt' | 'nb' | 'nl'
export const LANG_NAME: Record<Lang, string> = { en: 'English', pt: 'Português', nb: 'Norsk', nl: 'Nederlands' }
export const LOCAL_LANG: Record<string, Lang> = { Coimbra: 'pt', Oslo: 'nb', Ghent: 'nl', Gent: 'nl' }

/** The languages offered for a stream: the city's own language first, then English. */
export function languagesFor(city: string | undefined): Lang[] {
  const local = city ? LOCAL_LANG[city] : undefined
  return local ? [local, 'en'] : ['en']
}

/** The viewer's preferred language if it is offered, else English (a visitor), else the city's language. */
export function preferredLang(offered: Lang[]): Lang {
  const nav = (navigator.languages ?? [navigator.language ?? 'en']).map((l) => l.toLowerCase().slice(0, 2))
  const wanted = nav.map((l) => (l === 'no' || l === 'nn' ? 'nb' : l)).find((l) => offered.includes(l as Lang))
  return (wanted as Lang) ?? (offered.includes('en') ? 'en' : offered[0])
}

const en = {
  title: 'Report a sign of pollution', intro: 'Seen grey water, a sewage smell, foam or a pipe running in dry weather? Tell us where. It takes under a minute.',
  stream: 'Stream', where: 'Where are you?', useLoc: 'Use my location', tapHint: 'Or tap the map where you are standing by the stream.',
  picked: 'Location set', what: 'What do you see or smell?', none: 'Pick at least one sign, or send a report that the water looks clean.',
  clean: 'The water looks clean', send: 'Send report', sending: 'Sending…',
  photo: 'Add a photo (optional)', photoConsent: 'Photos are checked by an AI service to read the water. Location data is removed and faces are blurred first. Photos are deleted after the retention period.',
  thanks: 'Thank you. Your report is part of case', offline: 'You are offline. Your report is saved on this phone and will be sent automatically.',
  offlinePhoto: "A photo can't be saved offline, so it will not be sent.",
  queued: 'report(s) waiting to be sent', status: 'Case status', mission: 'Can you help narrow it down?', missionHelp: 'One short check nearby makes the search much faster:',
  go: 'Go to', lookFor: 'Look and smell for grey or milky water, a sewage smell, or a pipe running when it has not rained.',
  looksClean: 'Looks clean', polluted: 'Polluted', cantGo: "I can't go now", outcome: 'What your check did',
  narrowed: 'Thank you. Your check ruled out about {n}% of the places the source could be. The team sees it now.',
  noChange: 'Thank you. Your check confirmed what we knew; the team sees it now.',
  photoRead: 'Photo checked', photoNot: 'Photo not analysed', gotIt: 'Got it',
  conflictSeen: 'Your photo looks like it shows {f}. Your answer was kept.', conflictNotSeen: "We can't see {f} in your photo. Your answer was kept.",
  another: 'Report something else', safety: 'Stay on the bank. Do not touch the water or pipes.', advisory: 'Public advisory',
  faces: 'faces blurred (automatic detection can miss some)', farAway: 'That point is too far from the mapped stream. Move closer to the water.',
  landmark: 'Or choose the nearest point from a list', outfall: 'the outfall pipe at the marked spot', streamAt: 'the stream bank',
  about: 'about', fromYou: 'from where you reported', choose: 'Choose a point…', near: 'near', up: 'km above where the stream ends',
  language: 'Language',
}
type Strings = typeof en

const pt: Strings = {
  title: 'Comunicar um sinal de poluição', intro: 'Viu água cinzenta, cheiro a esgoto, espuma ou um tubo a descarregar sem chuva? Diga-nos onde. Demora menos de um minuto.',
  stream: 'Ribeira', where: 'Onde está?', useLoc: 'Usar a minha localização', tapHint: 'Ou toque no mapa onde está, junto à ribeira.',
  picked: 'Localização definida', what: 'O que vê ou cheira?', none: 'Escolha pelo menos um sinal, ou comunique que a água parece limpa.',
  clean: 'A água parece limpa', send: 'Enviar', sending: 'A enviar…',
  photo: 'Adicionar fotografia (opcional)', photoConsent: 'As fotografias são analisadas por um serviço de IA para ler a água. Primeiro, a localização é removida e os rostos são desfocados. As fotografias são apagadas no fim do prazo de conservação.',
  thanks: 'Obrigado. A sua comunicação faz parte do caso', offline: 'Está sem ligação. A comunicação ficou guardada neste telemóvel e será enviada automaticamente.',
  offlinePhoto: 'Não é possível guardar a fotografia sem ligação, por isso não será enviada.',
  queued: 'comunicação(ões) por enviar', status: 'Estado do caso', mission: 'Pode ajudar a localizar a origem?', missionHelp: 'Uma verificação rápida aqui perto acelera muito a procura:',
  go: 'Vá até', lookFor: 'Procure água cinzenta ou leitosa, cheiro a esgoto, ou um tubo a descarregar sem ter chovido.',
  looksClean: 'Parece limpa', polluted: 'Poluída', cantGo: 'Agora não posso', outcome: 'O que a sua verificação fez',
  narrowed: 'Obrigado. A sua verificação excluiu cerca de {n}% dos locais onde a origem podia estar. A equipa já a vê.',
  noChange: 'Obrigado. A sua verificação confirmou o que já sabíamos; a equipa já a vê.',
  photoRead: 'Fotografia verificada', photoNot: 'Fotografia não analisada', gotIt: 'Entendido',
  conflictSeen: 'A sua fotografia parece mostrar {f}. A sua resposta foi mantida.', conflictNotSeen: 'Não vemos {f} na sua fotografia. A sua resposta foi mantida.',
  another: 'Comunicar outra coisa', safety: 'Fique na margem. Não toque na água nem nos tubos.', advisory: 'Aviso público',
  faces: 'rostos desfocados (a deteção automática pode falhar alguns)', farAway: 'Esse ponto está longe da ribeira mapeada. Aproxime-se da água.',
  landmark: 'Ou escolha o ponto mais próximo numa lista', outfall: 'o tubo de descarga no local marcado', streamAt: 'a margem da ribeira',
  about: 'cerca de', fromYou: 'de onde comunicou', choose: 'Escolha um ponto…', near: 'perto de', up: 'km acima da foz da ribeira',
  language: 'Idioma',
}

const nb: Strings = {
  title: 'Meld tegn på forurensning', intro: 'Har du sett grått vann, kjent kloakklukt, sett skum eller et rør som renner i tørt vær? Fortell oss hvor. Det tar under ett minutt.',
  stream: 'Bekk', where: 'Hvor er du?', useLoc: 'Bruk posisjonen min', tapHint: 'Eller trykk på kartet der du står ved bekken.',
  picked: 'Posisjon valgt', what: 'Hva ser eller lukter du?', none: 'Velg minst ett tegn, eller meld at vannet ser rent ut.',
  clean: 'Vannet ser rent ut', send: 'Send melding', sending: 'Sender …',
  photo: 'Legg til bilde (valgfritt)', photoConsent: 'Bilder sjekkes av en KI-tjeneste som vurderer vannet. Først fjernes posisjonsdata og ansikter sløres. Bildene slettes etter lagringsperioden.',
  thanks: 'Takk. Meldingen din er en del av sak', offline: 'Du er frakoblet. Meldingen er lagret på telefonen og sendes automatisk.',
  offlinePhoto: 'Et bilde kan ikke lagres uten nett, så det blir ikke sendt.',
  queued: 'melding(er) venter på å bli sendt', status: 'Status for saken', mission: 'Kan du hjelpe oss å finne kilden?', missionHelp: 'En kort sjekk i nærheten gjør søket mye raskere:',
  go: 'Gå til', lookFor: 'Se og lukt etter grått eller melkeaktig vann, kloakklukt eller et rør som renner når det ikke har regnet.',
  looksClean: 'Ser rent ut', polluted: 'Forurenset', cantGo: 'Jeg kan ikke nå', outcome: 'Hva sjekken din gjorde',
  narrowed: 'Takk. Sjekken din utelukket omtrent {n} % av stedene kilden kunne være. Teamet ser den nå.',
  noChange: 'Takk. Sjekken din bekreftet det vi visste; teamet ser den nå.',
  photoRead: 'Bildet er sjekket', photoNot: 'Bildet ble ikke analysert', gotIt: 'Greit',
  conflictSeen: 'Bildet ditt ser ut til å vise {f}. Svaret ditt er beholdt.', conflictNotSeen: 'Vi ser ikke {f} på bildet ditt. Svaret ditt er beholdt.',
  another: 'Meld noe annet', safety: 'Hold deg på bredden. Ikke rør vannet eller rørene.', advisory: 'Offentlig råd',
  faces: 'ansikter sløret (automatisk gjenkjenning kan overse noen)', farAway: 'Det punktet er for langt fra den kartlagte bekken. Gå nærmere vannet.',
  landmark: 'Eller velg nærmeste punkt fra en liste', outfall: 'utløpsrøret på det markerte stedet', streamAt: 'bekkekanten',
  about: 'omtrent', fromYou: 'fra der du meldte', choose: 'Velg et punkt …', near: 'ved', up: 'km ovenfor bekkens utløp',
  language: 'Språk',
}

const nl: Strings = {
  title: 'Meld een teken van vervuiling', intro: 'Grijs water gezien, een rioollucht, schuim of een buis die loost bij droog weer? Laat ons weten waar. Het duurt minder dan een minuut.',
  stream: 'Beek', where: 'Waar bent u?', useLoc: 'Gebruik mijn locatie', tapHint: 'Of tik op de kaart waar u bij de beek staat.',
  picked: 'Locatie ingesteld', what: 'Wat ziet of ruikt u?', none: 'Kies minstens één teken, of meld dat het water er schoon uitziet.',
  clean: 'Het water ziet er schoon uit', send: 'Melding versturen', sending: 'Bezig met versturen…',
  photo: 'Foto toevoegen (optioneel)', photoConsent: 'Foto’s worden door een AI-dienst bekeken om het water te beoordelen. Eerst worden locatiegegevens verwijderd en gezichten vervaagd. Foto’s worden na de bewaartermijn verwijderd.',
  thanks: 'Bedankt. Uw melding hoort bij zaak', offline: 'U bent offline. Uw melding is op deze telefoon bewaard en wordt automatisch verstuurd.',
  offlinePhoto: 'Een foto kan niet offline bewaard worden en wordt dus niet verstuurd.',
  queued: 'melding(en) wachten op verzending', status: 'Status van de zaak', mission: 'Kunt u helpen de bron te vinden?', missionHelp: 'Eén korte controle in de buurt maakt de zoektocht veel sneller:',
  go: 'Ga naar', lookFor: 'Kijk en ruik of er grijs of melkachtig water is, een rioollucht, of een buis die loost terwijl het niet geregend heeft.',
  looksClean: 'Ziet er schoon uit', polluted: 'Vervuild', cantGo: 'Ik kan nu niet', outcome: 'Wat uw controle deed',
  narrowed: 'Bedankt. Uw controle sloot ongeveer {n}% uit van de plaatsen waar de bron kon zijn. Het team ziet het nu.',
  noChange: 'Bedankt. Uw controle bevestigde wat we al wisten; het team ziet het nu.',
  photoRead: 'Foto bekeken', photoNot: 'Foto niet geanalyseerd', gotIt: 'Begrepen',
  conflictSeen: 'Uw foto lijkt {f} te tonen. Uw antwoord is behouden.', conflictNotSeen: 'We zien geen {f} op uw foto. Uw antwoord is behouden.',
  another: 'Iets anders melden', safety: 'Blijf op de oever. Raak het water en de buizen niet aan.', advisory: 'Openbaar advies',
  faces: 'gezichten vervaagd (automatische herkenning kan er enkele missen)', farAway: 'Dat punt ligt te ver van de gekarteerde beek. Ga dichter bij het water staan.',
  landmark: 'Of kies het dichtstbijzijnde punt uit een lijst', outfall: 'de lozingsbuis op de gemarkeerde plek', streamAt: 'de oever',
  about: 'ongeveer', fromYou: 'van waar u meldde', choose: 'Kies een punt…', near: 'bij', up: 'km stroomopwaarts van de monding',
  language: 'Taal',
}

export const T: Record<Lang, Strings> = { en, pt, nb, nl }

export const FEATURES: { id: string; label: Record<Lang, string> }[] = [
  { id: 'grey', label: { en: 'Grey or milky water', pt: 'Água cinzenta ou leitosa', nb: 'Grått eller melkeaktig vann', nl: 'Grijs of melkachtig water' } },
  { id: 'sewage_odour', label: { en: 'Sewage smell', pt: 'Cheiro a esgoto', nb: 'Kloakklukt', nl: 'Rioollucht' } },
  { id: 'pipe_flowing', label: { en: 'Pipe discharging', pt: 'Tubo a descarregar', nb: 'Rør som renner', nl: 'Buis die loost' } },
  { id: 'foam', label: { en: 'Foam', pt: 'Espuma', nb: 'Skum', nl: 'Schuim' } },
  { id: 'brown_turbid', label: { en: 'Brown, muddy water', pt: 'Água castanha, turva', nb: 'Brunt, grumsete vann', nl: 'Bruin, troebel water' } },
  { id: 'green', label: { en: 'Green water or scum', pt: 'Água verde ou película', nb: 'Grønt vann eller hinne', nl: 'Groen water of drijflaag' } },
  { id: 'dead_fish', label: { en: 'Dead fish', pt: 'Peixes mortos', nb: 'Død fisk', nl: 'Dode vissen' } },
  { id: 'sewage_fungus', label: { en: 'Grey slimy growth', pt: 'Crescimento cinzento viscoso', nb: 'Grå, slimete begroing', nl: 'Grijze, slijmerige aangroei' } },
]

export const STATUS: Record<string, Record<Lang, string>> = {
  open: { en: 'Open', pt: 'Aberto', nb: 'Åpen', nl: 'Open' },
  localizing: { en: 'Searching for the source', pt: 'À procura da origem', nb: 'Leter etter kilden', nl: 'Op zoek naar de bron' },
  localized: { en: 'Source located', pt: 'Origem localizada', nb: 'Kilden er funnet', nl: 'Bron gevonden' },
  handed_off: { en: 'Sent to the water utility', pt: 'Enviado à entidade gestora', nb: 'Sendt til vann- og avløpsetaten', nl: 'Doorgegeven aan de waterbeheerder' },
  fixed: { en: 'Fixed', pt: 'Resolvido', nb: 'Utbedret', nl: 'Hersteld' },
  verified: { en: 'Fix verified', pt: 'Resolução confirmada', nb: 'Utbedring bekreftet', nl: 'Herstel bevestigd' },
  closed: { en: 'Closed', pt: 'Fechado', nb: 'Lukket', nl: 'Gesloten' },
  dismissed: { en: 'No pollution source found', pt: 'Sem origem de poluição', nb: 'Ingen forurensningskilde funnet', nl: 'Geen vervuilingsbron gevonden' },
}

/** A distance in km with one decimal, written the way the language writes it (3.5 or 3,5). */
export const km = (value: number, lang: Lang) => value.toLocaleString(lang === 'nb' ? 'nb-NO' : lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** Advisory text in the viewer's language if the case has it, else English. */
export const pick = (text: Partial<Record<string, string>> | null | undefined, lang: string) => text?.[lang] ?? text?.en ?? ''

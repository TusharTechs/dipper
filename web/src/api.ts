// Typed client for the Dipper API. Same origin in production (/api), proxied by Vite in development.

export type Role = 'citizen' | 'trained' | 'inspector' | 'public_health' | 'admin'
export type CheckType = 'instream_look' | 'outfall_look' | 'ammonium_strip' | 'lab_ecoli'

export interface Hypothesis { id: string; label: string; p: number; harmful: boolean }
export interface Source { id: string; label: string; p: number; lat: number; lon: number; synthetic: boolean; observable: boolean }
export interface RibbonPoint { node_id: string; lat: number; lon: number; p_polluted: number }
export interface LedgerEntry {
  index: number; text: string; kind: string; tier: string; weight_bans: number; weight_for: string; harm_bans: number
  entropy_before_bits: number; entropy_after_bits: number; p_harmful_before: number; p_harmful_after: number
  top_source_after: [string, number]
}
export interface ObservationView {
  kind: string; positive: boolean; role: string; tier: string; lat: number; lon: number; where: string
  observed_at: string | null; features: string[]
}
export interface Branch { probability: number; p_harmful: number; top_source: [string, number]; zone: string; zone_mass: number; advise: boolean }
export interface Recommendation {
  check: { check_type: CheckType; role: string; node_id: string | null; candidate_id: string | null; key: string }
  label: string; score: number; evsi: number; search_bits: number; cost: number; delay_h: number; p_positive: number
  if_positive: Branch; if_negative: Branch; changes_decision: boolean; reason: string
}
export interface Exposure { id: string; kind: string; label: string; lat: number; lon: number; p_affected: number; minutes_from_likely_source: number | null }
export interface Action { type: string; at: string; approver: string | null; payload: Record<string, unknown> }
export interface AdvisoryDraft {
  tiers: { observed: string; inferred: string; possible_risk: string; needs_confirmation: string }
  text: Record<string, string>; suggested: boolean
}
export interface CaseView {
  id: string; reach: string; city: string; status: string; opened_at: string; simulated?: boolean
  context: { regime: string; summary: string; rain_48h_mm: number | null; tmax_c: number | null; dry_days: number | null }
  hypotheses: Hypothesis[]; p_harmful: number; advisory_suggested: boolean; advisory_active: boolean; fix_confirmed_clean: boolean
  needs_trained_check: boolean; dismiss_proposed: boolean; stakes: number
  top_source: { id: string; label: string; p: number }; outside_or_unmapped: number; diffuse: number
  sources: Source[]; ribbon: RibbonPoint[]; ledger: LedgerEntry[]; observations: ObservationView[]
  unknowns: string[]; exposure: Exposure[]; recommendations: Recommendation[]; actions: Action[]
  advisory_draft: AdvisoryDraft; model: { version: string; note: string }
}
export interface CaseSummary {
  id: string; reach: string; city: string; status: string; opened_at: string; last_activity: string; simulated: boolean
  leading_hypothesis: Hypothesis; top_source: { id: string; label: string; p: number }; p_harmful: number; signals: number
}
export interface CitizenCase {
  id: string; reach: string; status: string; reports: number; checks: number
  mission: { key: string; type: CheckType; kind: 'outfall' | 'stream'; lat: number; lon: number; km_above_outlet: number
    walk_m: number | null } | null
  advisory: Record<string, string> | null; history: { at: string; type: string }[]
}
export interface PublicAdvisory {
  case: string; reach: string; city: string; issued_at: string; text: Record<string, string>
  stretch: { type: 'LineString'; coordinates: [number, number][] }; simulated: boolean
}
export interface HistoryEvent { seq: number; at: string; type: 'observation' | 'action'; payload: Record<string, any> }
export interface ReachInfo { id: string; name: string; city: string; length_m: number; candidates: number; places: number }
export interface User { id: string; name: string; role: Role; demo: boolean }
export interface Config { demo: boolean; roles: Role[]; demo_reach: string | null; fhir_server: boolean }
export interface SignalResult { case_id: string; status: string; snap_distance_m: number; report_token: string }
export interface PhotoResult {
  case_id: string; status: string; report_token: string
  photo: { status: 'analysed' | 'not_analysed'; reason?: string; faces_blurred: number; note?: string
    conflicts?: { feature: string; citizen_said: boolean; photo_confidence: number; prompt: string }[] }
}
export type GeoJSON = { type: 'FeatureCollection'; properties: Record<string, unknown>; features: GeoFeature[] }
export type GeoFeature = { type: 'Feature'; geometry: { type: string; coordinates: any }; properties: Record<string, any> }

// ---- session (per-viewer convenience; the server is the source of truth) ----
const TOKEN_KEY = 'dipper.token'
export const session = {
  get token(): string | null { try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null } },
  set(token: string | null) { try { token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } },
}

/** A random id kept on this device only. The server turns it into a keyed pseudonym; it is never a name or email. */
export function deviceId(): string {
  const key = 'dipper.device'
  try {
    let v = localStorage.getItem(key)
    if (!v) { v = 'd-' + crypto.randomUUID().replace(/-/g, '').slice(0, 20); localStorage.setItem(key, v) }
    return v
  } catch { return 'd-ephemeral' }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.body && !(init.body instanceof FormData) ? { 'content-type': 'application/json' } : {}) }
  const t = session.token
  if (t) headers.authorization = `Bearer ${t}`
  const r = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> ?? {}) } })
  if (!r.ok) {
    let detail = r.statusText
    try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg).join('; ') : detail } catch { /* not JSON */ }
    if (r.status === 401) session.set(null)
    throw new ApiError(r.status, detail)
  }
  return r.json() as Promise<T>
}
const enc = encodeURIComponent
const post = (body?: unknown): RequestInit => ({ method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  config: () => req<Config>('/v1/config'),
  me: () => req<User>('/v1/auth/me'),
  demoSignIn: (role: 'inspector' | 'public_health') => req<{ token: string; user: User }>('/v1/auth/demo', post({ role })),
  reaches: () => req<ReachInfo[]>('/v1/reaches'),
  reach: (id: string) => req<GeoJSON>(`/v1/reaches/${enc(id)}`),
  cases: () => req<CaseSummary[]>('/v1/cases'),
  case: (id: string) => req<CaseView>(`/v1/cases/${enc(id)}`),
  history: (id: string) => req<HistoryEvent[]>(`/v1/cases/${enc(id)}/history`),
  fhir: (id: string) => req<any>(`/v1/cases/${enc(id)}/fhir`),
  fhirPush: (id: string) => req<{ server: string; resources: number; created: number; updated: number }>(`/v1/cases/${enc(id)}/fhir/push`, post()),
  startScenario: (wet: boolean) => req<CaseView>(`/v1/scenarios/c014?wet=${wet}`, post()),
  autostep: (id: string) => req<{ performed: Recommendation; result: string; case: CaseView }>(`/v1/scenarios/${enc(id)}/autostep`, post()),
  check: (id: string, body: { check_type: CheckType; positive: boolean; node_id?: string | null; candidate_id?: string | null }) =>
    req<CaseView>(`/v1/cases/${enc(id)}/checks`, post(body)),
  action: (id: string, type: string, extra?: { note?: string; clean?: boolean }) => req<CaseView>(`/v1/cases/${enc(id)}/actions`, post({ type, ...extra })),
  signal: (body: { reach_id: string; lat: number; lon: number; features: Record<string, boolean>; observed_at?: string; client_id?: string }) =>
    req<SignalResult>('/v1/signals', post({ ...body, observer: deviceId() })),
  // The report token proves this device made the report; it travels in a header, never in the URL.
  citizenCase: (id: string, token: string) => req<CitizenCase>(`/v1/citizen/cases/${enc(id)}`, { headers: { 'x-report-token': token } }),
  citizenCheck: (id: string, token: string, mission_key: string, positive: boolean) =>
    req<{ status: string; search_narrowed_bits: number }>(`/v1/citizen/cases/${enc(id)}/checks`,
      { ...post({ mission_key, positive }), headers: { 'x-report-token': token } }),
  advisories: () => req<PublicAdvisory[]>('/v1/public/advisories'),
  simResults: () => req<any>('/v1/sim/results'),
  signalPhoto: (file: File, body: { reach_id: string; lat: number; lon: number; features: Record<string, boolean> }) => {
    const fd = new FormData()
    fd.append('photo', file); fd.append('reach_id', body.reach_id); fd.append('lat', String(body.lat)); fd.append('lon', String(body.lon))
    fd.append('features', JSON.stringify(body.features)); fd.append('observer', deviceId())
    return req<PhotoResult>('/v1/signals/photo', { method: 'POST', body: fd })
  },
}

export const DEFAULT_REACH = 'coimbra-ribeira-de-coselhas'
export const pct = (p: number) => `${Math.round(p * 100)}%`
export const STATUS_LABEL: Record<string, string> = {
  open: 'Open', localizing: 'Searching', localized: 'Source localized', handed_off: 'Handed to utility',
  fixed: 'Fixed', verified: 'Fix verified', closed: 'Closed', dismissed: 'Dismissed',
}

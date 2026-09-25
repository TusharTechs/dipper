// Typed client for the Dipper API (proxied at /api in dev).

export type Role = 'citizen' | 'trained' | 'inspector'
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
  kind: string; positive: boolean; role: Role; tier: string; lat: number; lon: number; where: string
  observed_at: string | null; features: string[]
}
export interface Branch { probability: number; p_harmful: number; top_source: [string, number]; zone: string; zone_mass: number; advise: boolean }
export interface Recommendation {
  check: { check_type: CheckType; role: Role; node_id: string | null; candidate_id: string | null; key: string }
  label: string; score: number; evsi: number; search_bits: number; cost: number; delay_h: number; p_positive: number
  if_positive: Branch; if_negative: Branch; changes_decision: boolean; reason: string
}
export interface Exposure { id: string; kind: string; label: string; lat: number; lon: number; p_affected: number; minutes_from_likely_source: number | null }
export interface CaseView {
  id: string; reach: string; city: string; status: string; opened_at: string
  context: { regime: string; summary: string; rain_48h_mm: number | null; tmax_c: number | null; dry_days: number | null }
  hypotheses: Hypothesis[]; p_harmful: number; advisory_suggested: boolean; stakes: number
  top_source: { id: string; label: string; p: number }; outside_or_unmapped: number; diffuse: number
  sources: Source[]; ribbon: RibbonPoint[]; ledger: LedgerEntry[]; observations: ObservationView[]
  unknowns: string[]; exposure: Exposure[]; recommendations: Recommendation[]
  actions: { type: string; at: string; approver: string | null; payload: Record<string, unknown> }[]
  model: { version: string; note: string }
  scenario?: { label: string }
}
export interface CaseSummary {
  id: string; reach: string; city: string; status: string; opened_at: string
  leading_hypothesis: Hypothesis; top_source: { id: string; label: string; p: number }; p_harmful: number; signals: number
}
export interface ReachInfo { id: string; name: string; city: string; length_m: number; candidates: number; places: number }
export type GeoJSON = { type: 'FeatureCollection'; properties: Record<string, unknown>; features: GeoFeature[] }
export type GeoFeature = { type: 'Feature'; geometry: { type: string; coordinates: any }; properties: Record<string, any> }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: { 'content-type': 'application/json' }, ...init })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return r.json() as Promise<T>
}

export const api = {
  reaches: () => req<ReachInfo[]>('/v1/reaches'),
  reach: (id: string) => req<GeoJSON>(`/v1/reaches/${encodeURIComponent(id)}`),
  cases: () => req<CaseSummary[]>('/v1/cases'),
  case: (id: string) => req<CaseView>(`/v1/cases/${id}`),
  recommendations: (id: string, roles: Role[], k = 3) =>
    req<Recommendation[]>(`/v1/cases/${id}/recommendations?k=${k}&roles=${roles.join(',')}`),
  startScenario: (wet: boolean) => req<CaseView>(`/v1/scenarios/c014?wet=${wet}`, { method: 'POST' }),
  autostep: (id: string) => req<{ performed: Recommendation; result: string; case: CaseView }>(`/v1/scenarios/${id}/autostep`, { method: 'POST' }),
  check: (id: string, body: { check_type: CheckType; positive: boolean; node_id?: string | null; candidate_id?: string | null; role: Role; observer?: string }) =>
    req<CaseView>(`/v1/cases/${id}/checks`, { method: 'POST', body: JSON.stringify(body) }),
  action: (id: string, type: string, approver: string | null, payload: Record<string, unknown> = {}) =>
    req<CaseView>(`/v1/cases/${id}/actions`, { method: 'POST', body: JSON.stringify({ type, approver, payload }) }),
  signal: (body: { reach_id: string; lat: number; lon: number; features: Record<string, boolean>; role: Role; observer?: string; case_id?: string }) =>
    req<{ case_id: string; snapped_node: string; snap_distance_m: number; status: string }>('/v1/signals', { method: 'POST', body: JSON.stringify(body) }),
}

export const REACH_ID = 'coimbra-ribeira-de-coselhas'

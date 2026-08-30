const BASE = import.meta.env.VITE_API_URL || ''

export type Health = { status: string; model_loaded: boolean; revision: string | null; detail?: string }
export type Ranking = { rank: number; gene: string; score: number; rwr: number; is_seed: boolean }
export type RankingsResponse = { total: number; limit: number; offset: number; results: Ranking[]; revision?: string }
export type GeneDetail = Ranking & { explanation: any }
export type Seed = { symbol: string; locus: string; trait: string; citation: string; pmid: string }

async function fetchJSON(url: string, opts?: RequestInit) {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const text = await res.text()
    let detail: string
    try { detail = JSON.parse(text).detail || text } catch { detail = text }
    const err: any = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  health: (): Promise<Health> => fetchJSON(`${BASE}/health`),
  rankings: (params: { limit?: number; offset?: number; q?: string } = {}): Promise<RankingsResponse> => {
    const sp = new URLSearchParams()
    if (params.limit) sp.set('limit', String(params.limit))
    if (params.offset) sp.set('offset', String(params.offset))
    if (params.q) sp.set('q', params.q)
    const qs = sp.toString()
    return fetchJSON(`${BASE}/rankings${qs ? '?' + qs : ''}`)
  },
  search: (q: string): Promise<{ query: string; results: Ranking[] }> =>
    fetchJSON(`${BASE}/genes/search?q=${encodeURIComponent(q)}`),
  gene: (symbol: string): Promise<GeneDetail> => fetchJSON(`${BASE}/genes/${encodeURIComponent(symbol)}`),
  explain: (gene: string): Promise<{ gene: string; ranking: Ranking; explanation: any }> =>
    fetchJSON(`${BASE}/explain/${encodeURIComponent(gene)}`),
  seeds: (): Promise<{ seeds: Seed[]; count: number }> => fetchJSON(`${BASE}/seeds`),
}

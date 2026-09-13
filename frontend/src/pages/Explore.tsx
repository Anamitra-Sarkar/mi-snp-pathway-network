import { useEffect, useState } from 'react'
import { api, Ranking, Seed } from '../api'

export default function Explore() {
  const [health, setHealth] = useState<{ model_loaded: boolean } | null>(null)
  const [rankings, setRankings] = useState<Ranking[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<any>(null)
  const [seeds, setSeeds] = useState<Seed[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [explainLoading, setExplainLoading] = useState(false)

  const loadRankings = async (q: string = query, nextOffset: number = 0) => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.rankings({ limit: 25, offset: nextOffset, q: q?.trim() || undefined })
      setRankings(res.results)
      setTotal(res.total)
      setOffset(nextOffset)
    } catch (e: any) {
      setError('Could not load rankings. Please try again.')
      setRankings([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    api.health().then(h => {
      setHealth(h)
      if (h.model_loaded) loadRankings('', 0)
    }).catch(() => setHealth({ model_loaded: false }))
    api.seeds().then(s => setSeeds(s.seeds)).catch(() => {})
  }, [])

  const onSelect = async (gene: string) => {
    setExplainLoading(true)
    try {
      const detail = await api.explain(gene)
      setSelected(detail)
    } catch (e: any) {
      setSelected({ gene, error: 'Could not load details. Please try again.' })
    } finally {
      setExplainLoading(false)
    }
  }

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (trimmed.length > 100) {
      setError('Query too long (max 100 chars)')
      return
    }
    loadRankings(trimmed, 0)
  }

  return (
    <main className="main">
      <div>
        <h1>Explore gene rankings</h1>
        <p className="lede">Scores reflect how closely each gene connects to known heart-disease risk genes through shared biology.</p>
      </div>

      <section className="card">
        <h2 id="search-heading">Search genes</h2>
        <form onSubmit={onSearch} className="search-row" aria-labelledby="search-heading">
          <label htmlFor="gene-search" className="sr-only">Search gene symbol</label>
          <input
            id="gene-search"
            className="input"
            placeholder="Search gene symbol (e.g. PCSK9, LDLR, 9p21)…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search gene symbol"
            autoComplete="off"
          />
          <button className="btn primary" type="submit" aria-label="Search">Search</button>
          <button className="btn" type="button" onClick={() => { setQuery(''); loadRankings('', 0) }} aria-label="Clear search">Clear</button>
        </form>
        <p className="hint" aria-live="polite">
          Known risk genes: {seeds.slice(0, 8).map(s => s.symbol).join(', ')}{seeds.length > 8 ? ` +${seeds.length - 8} more` : ''}{seeds.length === 0 ? ' (loading…)' : ''}
        </p>
      </section>

      <section className="card" aria-live="polite">
        <div className="table-header">
          <h3>Ranked genes</h3>
          <span className="muted">{total} genes ranked — showing {rankings.length} (offset {offset})</span>
        </div>
        {error && <div className="error" role="alert">{error}</div>}
        {loading ? <p aria-live="polite">Loading rankings…</p> : (
          <>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Ranked candidate genes for heart disease risk</caption>
              <thead>
                <tr>
                  <th scope="col">Rank</th>
                  <th scope="col">Gene</th>
                  <th scope="col">Score</th>
                  <th scope="col">Evidence</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rankings.map(r => (
                  <tr key={r.gene} className={r.is_seed ? 'is-seed' : ''}>
                    <td>#{r.rank}</td>
                    <td><strong>{r.gene}</strong> {r.is_seed && <span className="badge seed">Known risk gene</span>}</td>
                    <td>
                      <div className="score-cell">
                        <div className="bar" aria-hidden="true"><div className="fill" style={{ width: `${Math.min(100, r.score * 100)}%` }} /></div>
                        <span className="num">{r.score.toFixed(4)}</span>
                      </div>
                    </td>
                    <td className="muted">{r.is_seed ? 'Known heart-disease risk gene' : 'Network-linked candidate'}</td>
                    <td><button className="btn small" onClick={() => onSelect(r.gene)} aria-label={`Explain ${r.gene}`}>Explain</button></td>
                  </tr>
                ))}
                {rankings.length === 0 && <tr><td colSpan={5} className="muted">No results. Try a different query or clear filter.</td></tr>}
              </tbody>
            </table>
          </div>
          {total > 25 && (
            <div className="pagination" role="navigation" aria-label="Pagination">
              <button className="btn small" disabled={offset === 0 || loading} onClick={() => loadRankings(query, Math.max(0, offset - 25))}>Previous</button>
              <span className="muted" style={{padding: '6px 10px'}}>{offset + 1}–{Math.min(offset + rankings.length, total)} of {total}</span>
              <button className="btn small" disabled={offset + rankings.length >= total || loading} onClick={() => loadRankings(query, offset + 25)}>Next</button>
            </div>
          )}
          </>
        )}
      </section>

      {selected && (
        <section className="card detail" aria-live="polite">
          <div className="detail-head">
            <h3>Why {selected.gene} ranks here</h3>
            <button className="btn small" onClick={() => setSelected(null)} aria-label="Close explanation">Close</button>
          </div>
          {explainLoading ? <p>Loading explanation…</p> : selected.error ? <p className="error" role="alert">{selected.error}</p> : (
            <>
              <div className="grid2">
                <div><strong>Rank:</strong> #{selected.ranking?.rank}</div>
                <div><strong>Score:</strong> {selected.ranking?.score?.toFixed(4)}</div>
                <div><strong>Known risk gene:</strong> {selected.ranking?.is_seed ? 'Yes' : 'No — candidate'}</div>
              </div>
              <p className="note">{selected.explanation?.note}</p>
              {selected.explanation?.shared_pathways?.length > 0 ? (
                <>
                  <h4>Shared biological pathways with known risk genes</h4>
                  <ul>
                    {selected.explanation.shared_pathways.slice(0, 10).map((sp: any, i: number) => (
                      <li key={i}><code>{sp.pathway}</code> — shared with <strong>{sp.shared_with_seed}</strong></li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="muted">No shared pathway found with the current known-gene set. This score comes from protein-network closeness.</p>
              )}
            </>
          )}
        </section>
      )}

      <section className="card seeds">
        <h3>Established risk genes</h3>
        <p className="muted">Well-established heart disease and coronary artery disease risk genes from published genetic studies.</p>
        <div className="seed-grid">
          {(seeds.length ? seeds : [
            { symbol: 'CDKN2A/B (9p21.3)', locus: '9p21.3', trait: 'CAD/MI', citation: 'Helgadottir 2007', pmid: '17641190' },
            { symbol: 'LDLR', locus: '19p13', citation: 'MIGC 2009', pmid: '19198609', trait: 'CAD/MI' },
            { symbol: 'PCSK9', locus: '1p32', citation: 'Willer 2008', pmid: '18193043', trait: 'CAD/MI' },
          ] as any).slice(0, 20).map((s: any) => (
            <span key={s.symbol} className="seed-pill" title={`${s.citation} PMID:${s.pmid}`}>{s.symbol} <small>{s.locus}</small></span>
          ))}
        </div>
      </section>
      {health === null && <p className="muted">Checking model status…</p>}
    </main>
  )
}

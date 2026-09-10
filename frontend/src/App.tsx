import { useEffect, useState } from 'react'
import { api, Health, Ranking, Seed } from './api'

function HealthBanner({ health }: { health: Health | null }) {
  if (!health) return <div className="banner loading">Checking model status…</div>
  if (health.model_loaded) {
    return (
      <div className="banner ok">
        <span className="dot ok" /> Model loaded — revision <code>{health.revision}</code> — rankings are live.
      </div>
    )
  }
  return (
    <div className="banner warn" role="alert">
      <strong>Rankings aren't available yet</strong> — our team is finishing validation before enabling live results. This tool is for research exploration only, not clinical use.
    </div>
  )
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [rankings, setRankings] = useState<Ranking[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<any>(null)
  const [seeds, setSeeds] = useState<Seed[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [explainLoading, setExplainLoading] = useState(false)

  const loadHealth = async () => {
    try {
      const h = await api.health()
      setHealth(h)
      if (h.model_loaded) {
        try {
          const s = await api.seeds()
          setSeeds(s.seeds)
        } catch {
          // seeds always available even when model_loaded, but don't block health
        }
      } else {
        // still load seeds for display (endpoint is public even when gate closed)
        try {
          const s = await api.seeds()
          setSeeds(s.seeds)
        } catch {}
      }
    } catch (e: any) {
      setHealth({ status: 'error', model_loaded: false, revision: null, detail: e.message })
    }
  }

  const loadRankings = async (q: string = query, nextOffset: number = 0) => {
    if (!health?.model_loaded) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.rankings({ limit: 25, offset: nextOffset, q: q?.trim() || undefined })
      setRankings(res.results)
      setTotal(res.total)
      setOffset(nextOffset)
    } catch (e: any) {
      if (e.status === 503) {
        setError('Model not released — rankings unavailable (503).')
        setRankings([])
      } else if (e.status === 400 || e.status === 422) {
        setError(`Invalid query: ${e.message}`)
        setRankings([])
      } else {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadHealth()
  }, [])

  useEffect(() => {
    if (health?.model_loaded) loadRankings()
  }, [health?.model_loaded])

  const onSelect = async (gene: string) => {
    setExplainLoading(true)
    try {
      const detail = await api.explain(gene)
      setSelected(detail)
    } catch (e: any) {
      setSelected({ gene, error: e.message })
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
    <div className="app">
      <nav className="navbar">
        <div className="brand">
          <span className="brand-mark">MI</span>
          <span className="brand-name">Cardiac Gene Insight</span>
        </div>
      </nav>

      <section className="hero-section">
        <div className="hero-copy">
          <div className="eyebrow">Cardiovascular genetics</div>
          <h1>
            Trace heart disease risk <em>through</em> the gene network.
          </h1>
          <p className="lede">
            Cardiac Gene Insight ranks candidate genes for heart attack and coronary artery disease risk by how
            closely they connect to well-established risk genes — every ranking shows its reasoning, not just a score.
          </p>
          <a href="#workspace" className="btn primary">Explore rankings</a>
        </div>
        <figure className="hero-visual">
          <img
            src="/hero.png"
            alt="Illustration of a human heart in deep crimson at the center with coral-red branching vascular and gene-network lines extending outward, dotted with red and peach nodes representing protein-protein and pathway interactions for myocardial infarction and coronary artery disease research"
          />
        </figure>
      </section>

      <section className="feature-grid">
        <div className="feature-card">
          <span className="feature-index">01</span>
          <h3>Grounded in established risk</h3>
          <p>Well-studied cardiovascular risk genes anchor every search, keeping results tied to real biology.</p>
        </div>
        <div className="feature-card">
          <span className="feature-index">02</span>
          <h3>Explained, not just scored</h3>
          <p>Select any gene to see the shared biological pathways connecting it to known risk genes.</p>
        </div>
        <div className="feature-card">
          <span className="feature-index">03</span>
          <h3>Built for exploration</h3>
          <p>Search by gene symbol or known locus to quickly find and compare candidates.</p>
        </div>
      </section>

      <main id="workspace" className="main">
        <HealthBanner health={health} />

        <section className="card">
          <h2 id="search-heading">Search genes / variants</h2>
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
              disabled={!health?.model_loaded}
            />
            <button className="btn primary" type="submit" disabled={!health?.model_loaded} aria-label="Search">
              Search
            </button>
            <button className="btn" type="button" onClick={() => { setQuery(''); loadRankings('', 0) }} disabled={!health?.model_loaded} aria-label="Clear search">
              Clear
            </button>
          </form>
          <p className="hint" aria-live="polite">
            Known risk genes: {seeds.slice(0, 8).map(s => s.symbol).join(', ')}{seeds.length > 8 ? ` +${seeds.length - 8} more` : ''}{seeds.length === 0 ? ' (loading…)' : ''}
          </p>
          {health?.model_loaded === false && (
            <p className="hint"><button className="btn small" onClick={loadHealth}>Check again</button></p>
          )}
        </section>

        {!health?.model_loaded ? (
          <section className="card abstain">
            <h3>Rankings unavailable</h3>
            <p>Rankings aren't available yet. Our team is finishing validation on real cardiovascular genetics data before enabling live results.</p>
          </section>
        ) : (
          <>
            <section className="card" aria-live="polite">
              <div className="table-header">
                <h3>Ranked genes (fusion score = RWR + degree/PageRank + pathway overlap)</h3>
                <span className="muted">{total} genes ranked — showing {rankings.length} (offset {offset})</span>
              </div>
              {error && <div className="error" role="alert">{error}</div>}
              {loading ? <p aria-live="polite">Loading rankings…</p> : (
                <>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Ranked candidate genes for MI/CAD</caption>
                    <thead>
                      <tr>
                        <th scope="col">Rank</th>
                        <th scope="col">Gene</th>
                        <th scope="col">Score</th>
                        <th scope="col">RWR</th>
                        <th scope="col">Evidence</th>
                        <th scope="col"><span className="sr-only">Actions</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rankings.map(r => (
                        <tr key={r.gene} className={r.is_seed ? 'is-seed' : ''}>
                          <td>#{r.rank}</td>
                          <td><strong>{r.gene}</strong> {r.is_seed && <span className="badge seed">GWAS seed</span>}</td>
                          <td>
                            <div className="score-cell">
                              <div className="bar" aria-hidden="true"><div className="fill" style={{ width: `${Math.min(100, r.score * 100)}%` }} /></div>
                              <span className="num">{r.score.toFixed(4)}</span>
                            </div>
                          </td>
                          <td className="num">{r.rwr.toFixed(4)}</td>
                          <td className="muted">{r.is_seed ? 'Known MI/CAD risk gene' : 'Network-proximal candidate'}</td>
                          <td><button className="btn small" onClick={() => onSelect(r.gene)} aria-label={`Explain ${r.gene}`}>Explain</button></td>
                        </tr>
                      ))}
                      {rankings.length === 0 && <tr><td colSpan={6} className="muted">No results. Try a different query or clear filter.</td></tr>}
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
                  <h3>Explanation — {selected.gene}</h3>
                  <button className="btn small" onClick={() => setSelected(null)} aria-label="Close explanation">Close</button>
                </div>
                {explainLoading ? <p>Loading explanation…</p> : selected.error ? <p className="error" role="alert">{selected.error}</p> : (
                  <>
                    <div className="grid2">
                      <div><strong>Rank:</strong> #{selected.ranking?.rank}</div>
                      <div><strong>Fusion score:</strong> {selected.ranking?.score?.toFixed(4)}</div>
                      <div><strong>RWR score:</strong> {selected.explanation?.rwr_score?.toFixed(4) ?? selected.ranking?.rwr?.toFixed(4)}</div>
                      <div><strong>Is seed:</strong> {selected.ranking?.is_seed ? 'Yes (known GWAS hit)' : 'No — candidate'}</div>
                    </div>
                    <p className="note">{selected.explanation?.note}</p>
                    {selected.explanation?.shared_pathways?.length > 0 ? (
                      <>
                        <h4>Shared pathways with seed genes</h4>
                        <ul>
                          {selected.explanation.shared_pathways.slice(0, 10).map((sp: any, i: number) => (
                            <li key={i}><code>{sp.pathway}</code> — shared with seed <strong>{sp.shared_with_seed}</strong></li>
                          ))}
                        </ul>
                      </>
                    ) : (
                      <p className="muted">{typeof selected.explanation?.contributing_seeds === 'string' ? selected.explanation.contributing_seeds : 'No shared Reactome/KEGG pathway with current seed set (or pathway artifacts not deployed). Score driven by PPI proximity and topology.'}</p>
                    )}
                    <p className="hint">Scores combine network proximity to known risk genes with shared biological pathway evidence.</p>
                  </>
                )}
              </section>
            )}
          </>
        )}

        <section className="card seeds">
          <h3>Curated seed genes (GWAS Catalog EFO_0000612 / EFO_0000378 + literature)</h3>
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
      </main>

      <footer className="footer">
        <p>Research use only — not for clinical decision-making. Built on published genetic association studies and protein interaction data.</p>
      </footer>
    </div>
  )
}

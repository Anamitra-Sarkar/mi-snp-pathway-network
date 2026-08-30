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
      <strong>Model not yet released</strong> — rankings are unavailable or placeholder. {health.detail || 'Backend release gate is closed (MODEL_RELEASE_APPROVED != true).'} This UI abstains from showing clinical predictions until an approved model is loaded. Not for clinical use.
    </div>
  )
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [rankings, setRankings] = useState<Ranking[]>([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<any>(null)
  const [seeds, setSeeds] = useState<Seed[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadHealth = async () => {
    try {
      const h = await api.health()
      setHealth(h)
      if (h.model_loaded) {
        const s = await api.seeds()
        setSeeds(s.seeds)
      }
    } catch (e: any) {
      setHealth({ status: 'error', model_loaded: false, revision: null, detail: e.message })
    }
  }

  const loadRankings = async (q: string = query) => {
    if (!health?.model_loaded) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.rankings({ limit: 50, q: q || undefined })
      setRankings(res.results)
      setTotal(res.total)
    } catch (e: any) {
      if (e.status === 503) {
        setError('Model not released — rankings unavailable (503).')
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
    try {
      const detail = await api.explain(gene)
      setSelected(detail)
    } catch (e: any) {
      setSelected({ gene, error: e.message })
    }
  }

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    loadRankings(query)
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div>
            <h1>MI / CAD Gene Prioritization</h1>
            <p className="subtitle">SNP-gene-pathway network — RWR propagation from GWAS seeds over STRING PPI + Reactome/KEGG</p>
          </div>
          <div className="header-meta">
            <span className="tag">Cardiovascular Genetics</span>
            <span className="tag">GWAS Catalog · STRING · Reactome/KEGG</span>
          </div>
        </div>
      </header>

      <main className="main">
        <HealthBanner health={health} />

        <section className="card">
          <h2>Search genes / variants</h2>
          <form onSubmit={onSearch} className="search-row">
            <input
              className="input"
              placeholder="Search gene symbol (e.g. PCSK9, LDLR, 9p21)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="btn primary" type="submit" disabled={!health?.model_loaded}>
              Search
            </button>
            <button className="btn" type="button" onClick={() => { setQuery(''); loadRankings('') }} disabled={!health?.model_loaded}>
              Clear
            </button>
          </form>
          <p className="hint">
            Seeds: {seeds.slice(0, 8).map(s => s.symbol).join(', ')}{seeds.length > 8 ? ` +${seeds.length - 8} more` : ''} {seeds.length === 0 && health?.model_loaded ? '(loading…)' : seeds.length===0 ? '(model not loaded — seed list available via /seeds)' : ''}
          </p>
        </section>

        {!health?.model_loaded ? (
          <section className="card abstain">
            <h3>Rankings unavailable</h3>
            <p>The backend has not loaded an approved model artifact. This is the honest abstention state: no scores are fabricated. To enable rankings, deploy with <code>MODEL_RELEASE_APPROVED=true</code> and <code>APPROVED_ARTIFACT_REVISION</code> pointing at valid artifacts under <code>artifacts/</code> (see docs/architecture.md).</p>
            <p className="hint">Data sources: GWAS Catalog (EFO_0000612 / EFO_0000378), STRING v12 combined_score≥700, Reactome/KEGG pathways.</p>
          </section>
        ) : (
          <>
            <section className="card">
              <div className="table-header">
                <h3>Ranked genes (fusion score = RWR + degree/PageRank + pathway overlap)</h3>
                <span className="muted">{total} genes ranked — showing {rankings.length}</span>
              </div>
              {error && <div className="error">{error}</div>}
              {loading ? <p>Loading…</p> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Rank</th>
                        <th>Gene</th>
                        <th>Score</th>
                        <th>RWR</th>
                        <th>Evidence</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rankings.map(r => (
                        <tr key={r.gene} className={r.is_seed ? 'is-seed' : ''}>
                          <td>#{r.rank}</td>
                          <td><strong>{r.gene}</strong> {r.is_seed && <span className="badge seed">GWAS seed</span>}</td>
                          <td>
                            <div className="score-cell">
                              <div className="bar"><div className="fill" style={{ width: `${Math.min(100, r.score * 100)}%` }} /></div>
                              <span className="num">{r.score.toFixed(4)}</span>
                            </div>
                          </td>
                          <td className="num">{r.rwr.toFixed(4)}</td>
                          <td className="muted">{r.is_seed ? 'Known MI/CAD risk gene' : 'Network-proximal candidate'}</td>
                          <td><button className="btn small" onClick={() => onSelect(r.gene)}>Explain</button></td>
                        </tr>
                      ))}
                      {rankings.length === 0 && <tr><td colSpan={6} className="muted">No results. Try a different query or clear filter.</td></tr>}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {selected && (
              <section className="card detail">
                <div className="detail-head">
                  <h3>Explanation — {selected.gene}</h3>
                  <button className="btn small" onClick={() => setSelected(null)}>Close</button>
                </div>
                {selected.error ? <p className="error">{selected.error}</p> : (
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
                    <p className="hint">Method: RWR restart=0.3 over column-normalized STRING PPI (score≥700). Fusion: logistic regression on [RWR, degree, pagerank, pathway overlap]. Evaluation: LOSO recall@k + AUPRC vs degree baseline.</p>
                  </>
                )}
              </section>
            )}
          </>
        )}

        <section className="card seeds">
          <h3>Curated seed genes (GWAS Catalog EFO_0000612 / EFO_0000378 + literature)</h3>
          <p className="muted">Well-replicated MI/CAD risk loci. Production source of truth is GWAS Catalog REST API; hardcoded list here is citable and documented in docs/data_sources.md.</p>
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
        <p>Research use only — not for clinical decision-making. Sources: GWAS Catalog https://www.ebi.ac.uk/gwas/, STRING https://stringdb-downloads.org/, Reactome https://reactome.org/download-data, KEGG https://rest.kegg.jp/. Metrics: recall@k, AUPRC vs degree baseline.</p>
      </footer>
    </div>
  )
}

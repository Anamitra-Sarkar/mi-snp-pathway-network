import { Link } from 'react-router-dom'

export default function Home({ modelLoaded }: { modelLoaded: boolean }) {
  return (
    <>
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
          <Link to="/explore" className="btn primary">Explore rankings</Link>
          {modelLoaded && <span className="muted" style={{ marginLeft: '12px' }}>✓ Rankings are live</span>}
        </div>
        <figure className="hero-visual">
          <img
            src="/hero.png"
            alt="Illustration of a human heart with branching gene-network lines for heart disease research"
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
    </>
  )
}

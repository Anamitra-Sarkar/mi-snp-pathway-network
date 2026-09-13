import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, Health } from './api'
import Home from './pages/Home'
import Explore from './pages/Explore'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    api.health()
      .then(setHealth)
      .catch(() => setHealth({ status: 'error', model_loaded: false, revision: null }))
  }, [])

  return (
    <div className="app">
      <nav className="navbar">
        <div className="brand">
          <span className="brand-mark">MI</span>
          <span className="brand-name">Cardiac Gene Insight</span>
        </div>
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>Home</NavLink>
          <NavLink to="/explore" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>Explore</NavLink>
        </div>
      </nav>

      <Routes>
        <Route path="/" element={<Home modelLoaded={health?.model_loaded ?? false} />} />
        <Route path="/explore" element={<Explore />} />
      </Routes>

      <footer className="footer">
        <p>Research use only — not for clinical decision-making. Built on published genetic association studies and protein interaction data.</p>
      </footer>
    </div>
  )
}

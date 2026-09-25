import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import About from './About'
import Bench from './Bench'
import Citizen from './Citizen'
import PublicMap from './PublicMap'
import Queue from './Queue'
import SignIn from './SignIn'
import Workspace from './Workspace'
import { api, session, type Config, type User } from './api'

type Page = 'ops' | 'citizen' | 'public' | 'bench' | 'about'
type Route = { page: Page; caseId: string | null }

function parse(): Route {
  const [page, id] = window.location.hash.replace(/^#\/?/, '').split('/')
  const known: Page[] = ['ops', 'citizen', 'public', 'bench', 'about']
  return { page: known.includes(page as Page) ? (page as Page) : 'citizen', caseId: page === 'ops' && id ? decodeURIComponent(id) : null }
}

// ---- screen-reader announcements shared by every page ----
const AnnounceCtx = createContext<(msg: string) => void>(() => {})
export const useAnnounce = () => useContext(AnnounceCtx)

// ---- signed-in staff user ----
interface AuthState { user: User | null; config: Config | null; signIn: (token: string, user: User) => void; signOut: () => void }
const AuthCtx = createContext<AuthState>({ user: null, config: null, signIn: () => {}, signOut: () => {} })
export const useAuth = () => useContext(AuthCtx)

export default function App() {
  const [route, setRoute] = useState<Route>(parse)
  const [message, setMessage] = useState('')
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<Config | null>(null)

  useEffect(() => {
    const on = () => { setRoute(parse()); document.getElementById('main')?.focus() }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig({ demo: false, roles: [], demo_reach: null, fhir_server: false }))
    if (session.token) api.me().then(setUser).catch(() => setUser(null))
  }, [])
  useEffect(() => {
    const titles: Record<Page, string> = { ops: 'Operations', citizen: 'Report', public: 'Advisories', bench: 'SourceBench', about: 'How it works' }
    document.title = `${titles[route.page]} · Dipper`
  }, [route.page])

  const announce = useCallback((msg: string) => { setMessage(''); window.setTimeout(() => setMessage(msg), 50) }, [])
  const auth: AuthState = {
    user, config,
    signIn: (token, u) => { session.set(token); setUser(u); announce(`Signed in as ${u.name}`) },
    signOut: () => { session.set(null); setUser(null); announce('Signed out'); window.location.hash = '#/ops' },
  }

  // Short labels replace the full ones on narrow screens (CSS), so all five fit on a phone.
  const nav: { page: Page; label: string; short: string; href: string }[] = [
    { page: 'citizen', label: 'Report', short: 'Report', href: '#/citizen' },
    { page: 'public', label: 'Advisories', short: 'Advisories', href: '#/public' },
    { page: 'ops', label: 'Operations', short: 'Ops', href: route.caseId ? `#/ops/${encodeURIComponent(route.caseId)}` : '#/ops' },
    { page: 'bench', label: 'SourceBench', short: 'Bench', href: '#/bench' },
    { page: 'about', label: 'How it works', short: 'About', href: '#/about' },
  ]

  let body: ReactNode
  if (route.page === 'ops') body = !user ? <SignIn /> : route.caseId ? <Workspace caseId={route.caseId} /> : <Queue />
  else if (route.page === 'citizen') body = <Citizen />
  else if (route.page === 'public') body = <PublicMap />
  else if (route.page === 'bench') body = <Bench />
  else body = <About />

  return (
    <AuthCtx.Provider value={auth}>
      <AnnounceCtx.Provider value={announce}>
        <a className="skip" href="#main">Skip to content</a>
        <div className="app">
          <header className="top" role="banner">
            <a className="brand" href="#/citizen" aria-label="Dipper home"><img src="/icon.svg" alt="" width="30" height="30" />Dipper</a>
            <nav aria-label="Main">
              <ul>{nav.map((n) => (
                <li key={n.page}><a href={n.href} aria-current={route.page === n.page ? 'page' : undefined}
                  className={route.page === n.page ? 'on' : ''}><span className="full">{n.label}</span><span className="short">{n.short}</span></a></li>))}</ul>
            </nav>
            <span className="spacer" />
            {config?.demo && <span className="demo-badge" title="Demo mode: scenario replay and demo sign-in are enabled">Demo</span>}
            {user && route.page === 'ops' && <span className="who">{user.name}<span className="muted"> · {user.role.replace('_', ' ')}</span>
              <button className="small" onClick={auth.signOut}>Sign out</button></span>}
          </header>
          <main id="main" tabIndex={-1}>{body}</main>
          <footer className="foot">
            <span>Map data © OpenStreetMap contributors · Weather: Open-Meteo (CC BY 4.0)</span>
            <span>Prototype for the OneAquaHealth IEEE Global Hackathon 2026 · not affiliated with the OneAquaHealth consortium</span>
          </footer>
          <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{message}</div>
        </div>
      </AnnounceCtx.Provider>
    </AuthCtx.Provider>
  )
}

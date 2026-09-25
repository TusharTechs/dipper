import { useState } from 'react'
import { useAuth } from './App'
import { api, session } from './api'

export default function SignIn() {
  const { config, signIn } = useAuth()
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const withToken = async (t: string) => {
    setBusy(true); setError(null)
    session.set(t)
    try { signIn(t, await api.me()) } catch (e: any) { session.set(null); setError(e.message === 'sign in required' ? 'That token was not recognised or has expired.' : e.message) }
    finally { setBusy(false) }
  }
  const demo = async (role: 'inspector' | 'public_health') => {
    setBusy(true); setError(null)
    try { const r = await api.demoSignIn(role); signIn(r.token, r.user) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="center">
      <section className="card narrow" aria-labelledby="signin-h">
        <h1 id="signin-h">Staff sign-in</h1>
        <p className="muted">Case investigation, advisories and hand-offs are for authorised staff. Every approval is recorded under your name.</p>
        {config?.demo && (
          <div className="demo-box">
            <h2>Try the demo</h2>
            <p>Demo sign-in issues a 4-hour token. Choose the role you want to see:</p>
            <div className="row">
              <button className="primary" disabled={busy} onClick={() => demo('inspector')}>Continue as investigator</button>
              <button disabled={busy} onClick={() => demo('public_health')}>Continue as public-health officer</button>
            </div>
            <p className="muted small">Investigators run the search and hand off to the utility. Public-health officers approve advisories.</p>
          </div>
        )}
        <form onSubmit={(e) => { e.preventDefault(); if (token.trim()) withToken(token.trim()) }}>
          <label htmlFor="token">Access token</label>
          <input id="token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="dpr_…" aria-describedby="token-help" className="wide-input" />
          <p id="token-help" className="muted small">Your administrator creates it with <code>python -m dipper_api.admin create-user</code>.</p>
          <button type="submit" disabled={busy || !token.trim()}>Sign in</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </div>
  )
}

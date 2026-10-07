import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ArrowRight, CheckCircle2, Clock3, Compass, ExternalLink, LogOut, Radio, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { api } from "./api.js";

function Shell({ children, user, onLogout }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand"><span className="brand-mark"><Compass size={19} /></span><span>Luke’s Command Center</span></Link>
        {user && <nav><Link to="/">Home</Link><Link to="/tracker">Festival Tracker</Link><Link to="/account">Account</Link><button className="text-button" onClick={onLogout}><LogOut size={16} /> Log out</button></nav>}
      </header>
      <main>{children}</main>
      <footer>Built as the foundation for CSCI-GA.2630.</footer>
    </div>
  );
}

function AuthCard({ mode, onAuthenticated }) {
  const isRegister = mode === "register";
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const update = (event) => setForm({ ...form, [event.target.name]: event.target.value });
  async function submit(event) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      if (isRegister) {
        await api("/api/auth/register", { method: "POST", body: JSON.stringify(form) });
      }
      const login = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: form.username, password: form.password }) });
      localStorage.setItem("lukes_command_center_token", login.access_token);
      onAuthenticated(login.user);
      navigate("/");
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <section className="auth-layout">
      <div className="auth-copy">
        <span className="eyebrow"><Sparkles size={15} /> Your personal command center</span>
        <h1>{isRegister ? "Build from a secure foundation." : "Welcome back."}</h1>
        <p>{isRegister ? "Create the account that will carry your future tools, projects, and ideas." : "Sign in to return to your private workspace."}</p>
        <div className="trust-row"><ShieldCheck /><span>Argon2id passwords</span><CheckCircle2 /><span>Protected account routes</span></div>
      </div>
      <form className="glass-card auth-card" onSubmit={submit}>
        <div><p className="kicker">{isRegister ? "START HERE" : "SIGN IN"}</p><h2>{isRegister ? "Create your account" : "Access your command center"}</h2></div>
        <label>Username<input name="username" value={form.username} onChange={update} minLength="3" required autoComplete="username" placeholder="your_username" /></label>
        {isRegister && <label>Email<input name="email" type="email" value={form.email} onChange={update} required autoComplete="email" placeholder="you@example.com" /></label>}
        <label>Password<input name="password" type="password" value={form.password} onChange={update} minLength="8" required autoComplete={isRegister ? "new-password" : "current-password"} placeholder="At least 8 characters" /></label>
        {error && <div className="error-box">{error}</div>}
        <button className="primary-button" disabled={busy}>{busy ? "Please wait..." : isRegister ? "Create account" : "Log in"}<ArrowRight size={17} /></button>
        <p className="switch-copy">{isRegister ? "Already have an account?" : "New here?"} <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "Log in" : "Register"}</Link></p>
      </form>
    </section>
  );
}

function Home({ user }) {
  return <section className="dashboard"><div className="hero-panel"><span className="eyebrow"><span className="live-dot" /> SECURE SESSION ACTIVE</span><h1>Good to see you, <span>{user.username}</span>.</h1><p>Your command center tracks technologies that help friends find and communicate with each other when festival cell networks become congested.</p><Link className="primary-button inline" to="/tracker">Open Festival Tracker <ArrowRight size={17} /></Link></div><div className="status-grid"><article className="glass-card"><ShieldCheck /><p>IDENTITY</p><h3>Authenticated</h3><span>Bearer token verified by the API.</span></article><article className="glass-card"><UserRound /><p>PROFILE</p><h3>{user.email}</h3><span>Your persisted account record.</span></article><article className="glass-card accent-card"><Radio /><p>TRACKER</p><h3>Festival connectivity</h3><span>Research saved across repeated runs.</span></article></div></section>;
}

function safeWebUrl(value) { try { const url = new URL(value); return url.protocol === "https:" ? url.href : null; } catch { return null; } }

function TrackerItems({ title, items }) {
  return <section className="tracker-section"><h2>{title}</h2>{!items?.length ? <p className="empty-note">None this run.</p> : <div className="tracker-grid">{items.map((item, index)=><article className="glass-card tracker-card" key={item.key || `${title}-${index}`}><div className="tracker-card-top"><span>#{index + 1}</span><strong>{item.score ?? 0} relevance</strong></div><h3>{item.title}</h3><p>{item.summary}</p><dl><div><dt>Organization</dt><dd>{item.organization}</dd></div><div><dt>Technology</dt><dd>{item.technology}</dd></div><div><dt>Date</dt><dd>{item.date}</dd></div></dl><div className="source-list">{item.sources?.map((source, sourceIndex)=>{const href=safeWebUrl(source.url); return href ? <a key={sourceIndex} href={href} target="_blank" rel="noreferrer">{source.title || "Source"} <ExternalLink size={13}/></a> : <span key={sourceIndex}>{source.title || "Invalid source URL"}</span>})}</div></article>)}</div>}</section>;
}

function ArticleLog({ articles }) {
  return <section className="articles-section"><div className="section-heading"><div><span className="eyebrow">RESEARCH ACTIVITY</span><h2>Articles reviewed</h2></div><p>{articles?.length || 0} article events in this run</p></div>{!articles?.length ? <p className="empty-note">No articles were processed in this run.</p> : <div className="article-list">{articles.map((article, index)=>{const href=safeWebUrl(article.url); return <article className="glass-card article-row" key={`${article.url}-${article.time}-${index}`}><span className={`article-status ${article.status}`}>{article.status}</span><div className="article-info"><h3>{article.title || "Untitled article"}</h3>{href ? <a href={href} target="_blank" rel="noreferrer">{article.url} <ExternalLink size={13}/></a> : <span>{article.url || "No URL recorded"}</span>}</div><time>{article.time ? new Date(article.time).toLocaleString() : "Time unavailable"}</time></article>})}</div>}</section>;
}

function FestivalTracker() {
  const [latest, setLatest] = useState(null); const [runs, setRuns] = useState([]); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [openingRun, setOpeningRun] = useState("");
  useEffect(()=>{ Promise.all([api("/api/tracker/reports/latest").catch((err)=>err.status===404?null:Promise.reject(err)), api("/api/tracker/runs")]).then(([report, history])=>{setLatest(report); setRuns(history);}).catch((err)=>setError(err.message)).finally(()=>setLoading(false)); },[]);
  async function viewRun(runId) {
    setError(""); setOpeningRun(runId);
    try { const selected = await api(`/api/tracker/runs/${encodeURIComponent(runId)}`); setLatest(selected); window.scrollTo({ top: 0, behavior: "smooth" }); }
    catch (err) { setError(err.message); }
    finally { setOpeningRun(""); }
  }
  if (loading) return <section className="tracker-page"><p>Loading tracker…</p></section>;
  return <section className="tracker-page"><div className="tracker-hero"><span className="eyebrow"><Radio size={15}/> FESTIVAL CONNECTIVITY TRACKER</span><h1>Stay connected when festival networks fail.</h1><p>The agent researches products and festival pilots designed for communication or friend-finding when cellular networks are congested or unavailable.</p></div>{error && <div className="error-box">{error}</div>}{!latest ? <div className="glass-card no-report"><Radio/><h2>No report yet</h2><p>Run <code>python -m tracker run</code> from the project root, then refresh this page.</p></div> : <><div className="run-summary glass-card"><div><span>Status</span><strong>{latest.status}</strong></div><div><span>Viewing run</span><strong>{new Date(latest.completed_at).toLocaleString()}</strong></div><div><span>Model</span><strong>{latest.model}</strong></div><div><span>Top K</span><strong>{latest.k}</strong></div></div><TrackerItems title="New" items={latest.new_items}/><TrackerItems title="Still tracking" items={latest.still_items}/><TrackerItems title="Dropped from the Top K" items={latest.dropped_items}/><ArticleLog articles={latest.articles}/></>}<section className="history-section"><h2><Clock3 size={21}/> Run history</h2>{!runs.length ? <p className="empty-note">No saved runs.</p> : <div className="history-list">{runs.map((run)=><article className={`glass-card ${latest?.run_id===run.run_id ? "selected-run" : ""}`} key={run.run_id}><div><strong>{new Date(run.completed_at).toLocaleString()}</strong><span>{run.run_id}</span></div><span className={`status-pill ${run.status}`}>{run.status}</span><small>{run.articles?.filter((article)=>article.status==="fetched").length || 0} fetched · {run.articles?.filter((article)=>article.status==="skipped").length || 0} skipped · {run.articles?.filter((article)=>article.status==="rejected").length || 0} rejected</small><button className="view-run-button" onClick={()=>viewRun(run.run_id)} disabled={openingRun===run.run_id}>{openingRun===run.run_id ? "Opening…" : latest?.run_id===run.run_id ? "Viewing" : "View report"}</button></article>)}</div>}</section></section>;
}

function Account({ user, setUser, logout }) {
  const [email, setEmail] = useState(user.email); const [password, setPassword] = useState("");
  const [message, setMessage] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault(); setMessage(""); setError(""); setBusy(true);
    const payload = {}; if (email !== user.email) payload.email = email; if (password) payload.password = password;
    if (!Object.keys(payload).length) { setError("Change your email or enter a new password first."); setBusy(false); return; }
    try { const updated = await api(`/api/users/${user.id}`, { method: "PATCH", body: JSON.stringify(payload) }); setUser(updated); setPassword(""); setMessage("Account updated successfully."); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm("Delete your account permanently? This cannot be undone.")) return;
    try { await api(`/api/users/${user.id}`, { method: "DELETE" }); logout(); } catch (err) { setError(err.message); }
  }
  return <section className="account-layout"><div><span className="eyebrow">ACCOUNT SETTINGS</span><h1>Keep your identity current.</h1><p>Update your email or replace your password. Your username and account ID remain stable.</p></div><form className="glass-card account-card" onSubmit={save}><div className="identity-row"><span><UserRound /></span><div><strong>{user.username}</strong><small>ID: {user.id}</small></div></div><label>Email<input type="email" value={email} onChange={(e)=>setEmail(e.target.value)} required /></label><label>New password <small>(leave blank to keep current)</small><input type="password" value={password} onChange={(e)=>setPassword(e.target.value)} minLength="8" placeholder="At least 8 characters" /></label>{message && <div className="success-box">{message}</div>}{error && <div className="error-box">{error}</div>}<button className="primary-button" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button><div className="danger-zone"><div><strong>Delete account</strong><p>Permanently remove your account and profile.</p></div><button type="button" className="danger-button" onClick={remove}>Delete</button></div></form></section>;
}

function App() {
  const [user, setUser] = useState(null); const [loading, setLoading] = useState(true);
  function logout(){ localStorage.removeItem("lukes_command_center_token"); setUser(null); }
  useEffect(()=>{ if(!localStorage.getItem("lukes_command_center_token")){setLoading(false); return;} api("/api/auth/me").then(setUser).catch(logout).finally(()=>setLoading(false)); },[]);
  if (loading) return <div className="loading-screen"><Compass /> Loading Luke’s Command Center...</div>;
  return <Shell user={user} onLogout={logout}><Routes><Route path="/login" element={user ? <Navigate to="/"/> : <AuthCard mode="login" onAuthenticated={setUser}/>} /><Route path="/register" element={user ? <Navigate to="/"/> : <AuthCard mode="register" onAuthenticated={setUser}/>} /><Route path="/account" element={user ? <Account user={user} setUser={setUser} logout={logout}/> : <Navigate to="/login"/>} /><Route path="/tracker" element={user ? <FestivalTracker/> : <Navigate to="/login"/>} /><Route path="/" element={user ? <Home user={user}/> : <Navigate to="/login"/>} /><Route path="*" element={<Navigate to="/"/>}/></Routes></Shell>;
}
export default App;

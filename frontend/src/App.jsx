import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { ArrowRight, CheckCircle2, Compass, LogOut, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { api } from "./api.js";

function Shell({ children, user, onLogout }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand"><span className="brand-mark"><Compass size={19} /></span><span>Luke’s Command Center</span></Link>
        {user && <nav><Link to="/">Home</Link><Link to="/account">Account</Link><button className="text-button" onClick={onLogout}><LogOut size={16} /> Log out</button></nav>}
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
  return <section className="dashboard"><div className="hero-panel"><span className="eyebrow"><span className="live-dot" /> SECURE SESSION ACTIVE</span><h1>Good to see you, <span>{user.username}</span>.</h1><p>This is your empty room for Assignment 2. The foundation is live: identity, persistence, and protected APIs.</p><Link className="primary-button inline" to="/account">Manage account <ArrowRight size={17} /></Link></div><div className="status-grid"><article className="glass-card"><ShieldCheck /><p>IDENTITY</p><h3>Authenticated</h3><span>Bearer token verified by the API.</span></article><article className="glass-card"><UserRound /><p>PROFILE</p><h3>{user.email}</h3><span>Your persisted account record.</span></article><article className="glass-card accent-card"><Compass /><p>NEXT</p><h3>Furnish the room</h3><span>Add your everyday tools in A2.</span></article></div></section>;
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
  return <Shell user={user} onLogout={logout}><Routes><Route path="/login" element={user ? <Navigate to="/"/> : <AuthCard mode="login" onAuthenticated={setUser}/>} /><Route path="/register" element={user ? <Navigate to="/"/> : <AuthCard mode="register" onAuthenticated={setUser}/>} /><Route path="/account" element={user ? <Account user={user} setUser={setUser} logout={logout}/> : <Navigate to="/login"/>} /><Route path="/" element={user ? <Home user={user}/> : <Navigate to="/login"/>} /><Route path="*" element={<Navigate to="/"/>}/></Routes></Shell>;
}
export default App;

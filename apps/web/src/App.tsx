import { useState, useEffect } from 'react';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '';
const MASTER_SUITE_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

export default function App() {
  const [health, setHealth] = useState<any>(null);
  const [intent, setIntent] = useState('I want to create a 30-second energetic dance Reel');
  const [details, setDetails] = useState('Bollywood-inspired, Gen-Z audience, high energy');
  const [ownerId] = useState('00000000-0000-0000-0000-000000000001');
  const [step, setStep] = useState(1);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then(res => res.json())
      .then(data => setHealth(data))
      .catch(() => setHealth({ status: 'offline' }));
  }, []);

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/creation/intents`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer dev:${ownerId}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ primary_text: intent, details_text: details }),
      });
      const data = await res.json();
      setResult(data);
      setStep(2);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--paper)', color: 'var(--ink)' }}>
      <header style={{ borderBottom: 'var(--border)', padding: '16px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#fff' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ background: 'var(--lime)', border: 'var(--border)', padding: '6px 12px', fontWeight: 800, fontSize: '18px', transform: 'rotate(-1deg)' }}>
            GenZCreators
          </div>
          <span style={{ color: 'var(--muted)', fontSize: '13px', fontWeight: 600 }}>Intent-Driven Creator Operating System</span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span className="badge badge-ai">Grok / Dev AI</span>
          <span className="badge" style={{ background: health?.ok || health?.status === 'ok' ? 'var(--lime)' : 'var(--cyan)' }}>
            API: {health?.status || 'Active'}
          </span>
          <a href={`${MASTER_SUITE_URL}/`} target="_blank" rel="noreferrer" className="btn" style={{ fontSize: '12px', padding: '6px 14px' }}>
            Open Master Suite &rarr;
          </a>
        </div>
      </header>

      <main style={{ maxWidth: '1080px', margin: '32px auto', padding: '0 20px' }}>
        <div className="card" style={{ borderTop: '8px solid var(--lime)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '14px' }}>
            <div>
              <span className="badge badge-ai" style={{ marginBottom: '6px' }}>Intent Engine</span>
              <h2 style={{ fontSize: '24px' }}>What do you want to create today?</h2>
            </div>
            <span className="badge">Round 2 Ready</span>
          </div>

          <p style={{ color: 'var(--muted)', marginBottom: '16px' }}>
            Type your vision in natural language. GenZCreators synthesizes the workflow, scripts, camera plan, and edits automatically.
          </p>

          <div style={{ marginBottom: '14px' }}>
            <label style={{ fontWeight: 700, display: 'block', marginBottom: '6px' }}>Creation Intent</label>
            <textarea
              value={intent}
              onChange={e => setIntent(e.target.value)}
              style={{ width: '100%', minHeight: '80px', padding: '12px', border: 'var(--border)', fontSize: '15px' }}
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ fontWeight: 700, display: 'block', marginBottom: '6px' }}>Details / Audience / Vibe</label>
            <input
              type="text"
              value={details}
              onChange={e => setDetails(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: 'var(--border)', fontSize: '14px' }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              className="btn"
              onClick={handleAnalyze}
              disabled={loading}
              style={{ background: 'var(--purple)', color: '#fff', fontSize: '16px', padding: '12px 24px' }}
            >
              {loading ? 'Analyzing with AI Gateway...' : '⚡ Build Creation Plan'}
            </button>
            <span style={{ color: 'var(--muted)', fontSize: '13px' }}>
              Connected to <code>FastAPI @ :8000</code>
            </span>
          </div>
        </div>

        {step === 2 && result && (
          <div className="card" style={{ borderTop: '8px solid var(--purple)' }}>
            <span className="badge badge-ai" style={{ marginBottom: '8px' }}>Parsed Intent Output</span>
            <h3 style={{ fontSize: '20px', marginBottom: '12px' }}>Workflow Generated Successfully</h3>
            <pre className="mono" style={{ background: 'var(--paper)', padding: '16px', border: 'var(--border-thin)', overflowX: 'auto', fontSize: '13px' }}>
              {JSON.stringify(result, null, 2)}
            </pre>
            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
              <a href={`${MASTER_SUITE_URL}/`} target="_blank" rel="noreferrer" className="btn">
                Launch 14-Stage Visual Experience &rarr;
              </a>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

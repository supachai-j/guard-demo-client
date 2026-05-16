import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Pause, Play, Trash2, ChevronDown, ChevronUp, Volume2, VolumeX } from 'lucide-react';
import { apiService } from '../services/api';

type AuditEvent = {
  id: number;
  created_at: string | null;
  session_id: string | null;
  conversation_id: number | null;
  user_message: string;
  llm_provider: string | null;
  llm_model: string | null;
  guardrail_provider: string | null;
  guardrail_flagged: boolean;
  blocked: boolean;
  latency_ms: number | null;
};

const MAX_EVENTS = 20;
const STORAGE_KEY = 'attack_feed_state';

type Persisted = { collapsed: boolean; paused: boolean; sound: boolean };

const loadState = (): Persisted => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { collapsed: false, paused: false, sound: false, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { collapsed: false, paused: false, sound: false };
};

const saveState = (s: Persisted) => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch { /* ignore */ }
};

// Minimal WebAudio beep so we don't ship an audio asset.
const playPing = () => {
  try {
    const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.value = 0.05;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    osc.stop(ctx.currentTime + 0.2);
    setTimeout(() => ctx.close().catch(() => {}), 250);
  } catch { /* ignore */ }
};

const timeAgo = (iso: string | null): string => {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const diff = Math.max(0, Date.now() - t) / 1000;
  if (diff < 5) return 'just now';
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
};

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

const AttackFeed: React.FC = () => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [{ collapsed, paused, sound }, setUi] = useState<Persisted>(loadState);
  const esRef = useRef<EventSource | null>(null);
  const pausedRef = useRef(paused);
  const soundRef = useRef(sound);
  // Force re-render every 30s so the "Xs ago" labels stay fresh.
  const [, setTick] = useState(0);

  // Keep refs in sync so the EventSource callback always reads current values.
  pausedRef.current = paused;
  soundRef.current = sound;

  const persist = (next: Partial<Persisted>) => {
    setUi(prev => {
      const merged = { ...prev, ...next };
      saveState(merged);
      return merged;
    });
  };

  useEffect(() => {
    const url = apiService.auditStreamUrl({ flaggedOnly: true });
    if (!url) return; // Not authenticated — nothing to subscribe to.

    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener('hello', () => setConnected(true));
    es.addEventListener('audit', (ev: MessageEvent) => {
      if (pausedRef.current) return;
      try {
        const parsed: AuditEvent = JSON.parse(ev.data);
        setEvents(prev => [parsed, ...prev].slice(0, MAX_EVENTS));
        if (soundRef.current) playPing();
      } catch { /* ignore malformed event */ }
    });
    es.onerror = () => setConnected(false);
    es.onopen = () => setConnected(true);

    const tick = window.setInterval(() => setTick(x => x + 1), 30_000);

    return () => {
      es.close();
      esRef.current = null;
      window.clearInterval(tick);
    };
  }, []);

  // Don't show the widget at all if we don't have a token — saves a useless
  // EventSource connection on the public landing page.
  if (!apiService.auditStreamUrl({ flaggedOnly: true })) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[22rem] max-w-[92vw] shadow-2xl rounded-lg border border-red-300 dark:border-red-700/60 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-red-600 text-white">
        <div className="flex items-center gap-2 min-w-0">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span className="font-semibold text-sm">Live attack feed</span>
          <span
            className={`inline-block w-2 h-2 rounded-full ${connected ? 'bg-emerald-300 animate-pulse' : 'bg-gray-300'}`}
            title={connected ? 'Connected' : 'Disconnected'}
          />
          {events.length > 0 && (
            <span className="ml-1 text-[11px] font-semibold bg-white/20 px-1.5 py-0.5 rounded">
              {events.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => persist({ sound: !sound })}
            title={sound ? 'Mute alerts' : 'Play sound on alert'}
            className="p-1 rounded hover:bg-white/10"
          >
            {sound ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          </button>
          <button
            onClick={() => persist({ paused: !paused })}
            title={paused ? 'Resume' : 'Pause'}
            className="p-1 rounded hover:bg-white/10"
          >
            {paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
          </button>
          <button
            onClick={() => setEvents([])}
            title="Clear"
            className="p-1 rounded hover:bg-white/10"
          >
            <Trash2 className="w-4 h-4" />
          </button>
          <button
            onClick={() => persist({ collapsed: !collapsed })}
            title={collapsed ? 'Expand' : 'Collapse'}
            className="p-1 rounded hover:bg-white/10"
          >
            {collapsed ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="max-h-[60vh] overflow-y-auto divide-y divide-gray-100 dark:divide-slate-700">
          {events.length === 0 ? (
            <div className="p-4 text-sm text-gray-500 dark:text-slate-400 text-center">
              {paused
                ? 'Paused. Resume to receive new alerts.'
                : connected
                  ? 'Waiting for a flagged event…'
                  : 'Connecting…'}
            </div>
          ) : (
            events.map(e => (
              <div key={e.id} className="p-3 text-xs hover:bg-red-50/60 dark:hover:bg-red-900/10">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      e.blocked
                        ? 'bg-red-600 text-white'
                        : 'bg-amber-500 text-white'
                    }`}
                  >
                    {e.blocked ? 'BLOCKED' : 'MONITORED'}
                  </span>
                  <span className="font-medium text-gray-700 dark:text-slate-200 truncate">
                    {e.guardrail_provider || 'guardrail'}
                  </span>
                  <span className="ml-auto text-gray-400 dark:text-slate-500 whitespace-nowrap">
                    {timeAgo(e.created_at)}
                  </span>
                </div>
                <div className="text-gray-800 dark:text-slate-100 mb-1 break-words">
                  {clip(e.user_message || '(empty prompt)', 160)}
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-gray-500 dark:text-slate-400">
                  {e.llm_provider && <span>llm: {e.llm_provider}{e.llm_model ? ` · ${e.llm_model}` : ''}</span>}
                  {e.latency_ms != null && <span>{e.latency_ms} ms</span>}
                  {e.session_id && <span>sess: {clip(e.session_id, 8)}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default AttackFeed;

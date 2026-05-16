import React, { useEffect, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Lock, AlertTriangle, Loader2 } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';

const Login: React.FC = () => {
  const { token, loading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from?.pathname || '/admin';

  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [warnDefault, setWarnDefault] = useState(false);

  useEffect(() => {
    fetch('/api/auth/status')
      .then((r) => r.json())
      .then((d) => setWarnDefault(!!d?.warn_default_password))
      .catch(() => {});
  }, []);

  if (!loading && token) return <Navigate to={from} replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (e: any) {
      setError(e?.message || 'Login failed');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-slate-900 px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm bg-white dark:bg-slate-800 rounded-2xl shadow-xl border border-gray-200 dark:border-slate-700 p-6 space-y-4"
      >
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-900/40 flex items-center justify-center">
            <Lock className="w-5 h-5 text-primary-600 dark:text-primary-300" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 dark:text-slate-100">Admin sign in</h1>
            <p className="text-xs text-gray-500 dark:text-slate-400">guard-demo-client</p>
          </div>
        </div>

        {warnDefault && (
          <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/40 text-xs text-amber-800 dark:text-amber-200">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              Default credentials in use (<code>admin</code> / <code>admin</code>). Set
              <code className="mx-1">ADMIN_USER</code> + <code>ADMIN_PASSWORD</code> in env before exposing this instance.
            </span>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">Username</label>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">Password</label>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
            required
            autoFocus
          />
        </div>

        {error && (
          <div className="text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-500/15 border border-red-200 dark:border-red-500/40 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={pending || !username.trim() || !password}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
        >
          {pending ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in…</> : 'Sign in'}
        </button>

        <p className="text-xs text-gray-500 dark:text-slate-400 text-center">
          JWT-based admin auth · 12h sessions · token persists in localStorage
        </p>
      </form>
    </div>
  );
};

export default Login;

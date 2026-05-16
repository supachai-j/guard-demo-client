/**
 * Auth context — JWT token storage + login/logout helpers.
 *
 * Token lives in `localStorage` under `admin_token` so refresh survives. We
 * also keep the username + expiry in state for convenience (timestamps are
 * useful for the AdminConsole "session expires in X" footer).
 *
 * apiService reads `localStorage.admin_token` directly when it builds
 * request headers, so any component that triggers `login()` / `logout()`
 * doesn't need to thread the token explicitly.
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

interface AuthState {
  token: string | null;
  user: string | null;
  expiresAt: string | null;
  loading: boolean;
  authEnabled: boolean;
}

interface AuthContextValue extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const STORAGE_KEY = 'admin_token';
const STORAGE_USER = 'admin_user';
const STORAGE_EXP = 'admin_token_exp';

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<AuthState>(() => ({
    token: localStorage.getItem(STORAGE_KEY),
    user: localStorage.getItem(STORAGE_USER),
    expiresAt: localStorage.getItem(STORAGE_EXP),
    loading: true,
    authEnabled: true,
  }));

  const persist = (token: string | null, user: string | null, expiresAt: string | null) => {
    if (token) localStorage.setItem(STORAGE_KEY, token); else localStorage.removeItem(STORAGE_KEY);
    if (user) localStorage.setItem(STORAGE_USER, user); else localStorage.removeItem(STORAGE_USER);
    if (expiresAt) localStorage.setItem(STORAGE_EXP, expiresAt); else localStorage.removeItem(STORAGE_EXP);
  };

  const refresh = useCallback(async () => {
    try {
      const statusResp = await fetch('/api/auth/status');
      const statusData = await statusResp.json();
      const authEnabled = !!statusData?.enabled;
      const tok = localStorage.getItem(STORAGE_KEY);
      if (tok) {
        // Validate the stored token; clear on 401.
        const meResp = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${tok}` } });
        if (meResp.ok) {
          const me = await meResp.json();
          setState({
            token: tok,
            user: me.user || localStorage.getItem(STORAGE_USER),
            expiresAt: me.expires_at || localStorage.getItem(STORAGE_EXP),
            loading: false,
            authEnabled,
          });
          return;
        }
        // expired / invalid — purge
        persist(null, null, null);
      }
      setState({ token: null, user: null, expiresAt: null, loading: false, authEnabled });
    } catch {
      setState((s) => ({ ...s, loading: false }));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!resp.ok) {
      const body = await resp.text();
      let detail = body;
      try { detail = JSON.parse(body).detail || body; } catch { /* keep raw */ }
      throw new Error(detail || 'Login failed');
    }
    const data = await resp.json();
    persist(data.access_token, data.user, data.expires_at);
    setState({
      token: data.access_token,
      user: data.user,
      expiresAt: data.expires_at,
      loading: false,
      authEnabled: true,
    });
  }, []);

  const logout = useCallback(async () => {
    const tok = localStorage.getItem(STORAGE_KEY);
    if (tok) {
      try {
        await fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${tok}` } });
      } catch { /* fire-and-forget */ }
    }
    persist(null, null, null);
    setState((s) => ({ ...s, token: null, user: null, expiresAt: null }));
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
};

export const getStoredToken = (): string | null => localStorage.getItem(STORAGE_KEY);

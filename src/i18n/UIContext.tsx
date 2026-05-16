// UIContext — combines language (EN/TH) and color-mode (light/dark) so
// every component can read both via one tiny hook. Persists to localStorage.

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Dict, EN, Lang, LOCALES } from './locales';

type ColorMode = 'light' | 'dark';

interface UICtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
  t: (key: keyof Dict) => string;
  mode: ColorMode;
  setMode: (m: ColorMode) => void;
  toggleMode: () => void;
}

const Ctx = createContext<UICtx | null>(null);

const LANG_KEY = 'lang';
const MODE_KEY = 'color-mode';

const readLang = (): Lang => {
  try {
    const v = localStorage.getItem(LANG_KEY);
    return v === 'th' ? 'th' : 'en';
  } catch {
    return 'en';
  }
};

const readMode = (): ColorMode => {
  try {
    const v = localStorage.getItem(MODE_KEY);
    if (v === 'dark' || v === 'light') return v;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
};

const applyModeToDom = (mode: ColorMode) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (mode === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
  root.dataset.colorMode = mode;
};

export const UIProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<Lang>(() => readLang());
  const [mode, setModeState] = useState<ColorMode>(() => readMode());

  useEffect(() => { applyModeToDom(mode); }, [mode]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(LANG_KEY, l); } catch {}
  }, []);

  const setMode = useCallback((m: ColorMode) => {
    setModeState(m);
    try { localStorage.setItem(MODE_KEY, m); } catch {}
  }, []);

  const toggleLang = useCallback(() => setLang(lang === 'en' ? 'th' : 'en'), [lang, setLang]);
  const toggleMode = useCallback(() => setMode(mode === 'light' ? 'dark' : 'light'), [mode, setMode]);

  const t = useCallback((key: keyof Dict) => {
    const dict = LOCALES[lang] || EN;
    return dict[key] || EN[key] || (key as string);
  }, [lang]);

  const value = useMemo(
    () => ({ lang, setLang, toggleLang, t, mode, setMode, toggleMode }),
    [lang, setLang, toggleLang, t, mode, setMode, toggleMode]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
};

export const useUI = (): UICtx => {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useUI must be used within <UIProvider>');
  return ctx;
};

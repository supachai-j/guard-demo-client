import React from 'react';
import { Moon, Sun } from 'lucide-react';
import { useUI } from '../i18n/UIContext';

const UIToggles: React.FC = () => {
  const { lang, setLang, mode, toggleMode, t } = useUI();

  return (
    <div className="flex items-center gap-1.5">
      {/* EN / TH segmented control */}
      <div className="flex items-center text-xs font-medium border border-gray-300 dark:border-slate-600 rounded-md overflow-hidden">
        <button
          type="button"
          onClick={() => setLang('en')}
          className={`px-2 py-1 transition-colors ${
            lang === 'en'
              ? 'bg-primary-600 text-white'
              : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700'
          }`}
          aria-pressed={lang === 'en'}
        >
          EN
        </button>
        <button
          type="button"
          onClick={() => setLang('th')}
          className={`px-2 py-1 transition-colors ${
            lang === 'th'
              ? 'bg-primary-600 text-white'
              : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700'
          }`}
          aria-pressed={lang === 'th'}
        >
          TH
        </button>
      </div>

      {/* Light / Dark toggle */}
      <button
        type="button"
        onClick={toggleMode}
        className="p-1.5 rounded-md border border-gray-300 dark:border-slate-600 text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
        aria-label={t('toggleTheme')}
        title={t('toggleTheme')}
      >
        {mode === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>
    </div>
  );
};

export default UIToggles;

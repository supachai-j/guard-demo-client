import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Download, Eye, EyeOff, ChevronDown, ChevronRight } from 'lucide-react';
import { AppConfig, AppConfigUpdate, ProviderInfo, GuardrailProviderInfo } from '../types';
import { apiService } from '../services/api';
import UploadDropzone from '../components/UploadDropzone';
import ToolManager from '../components/ToolManager';
import GenerateContentModal from '../components/GenerateContentModal';
import RagManagement, { RagManagementRef } from '../components/RagManagement';
import DemoPromptManager from '../components/DemoPromptManager';
import UIToggles from '../components/UIToggles';
import ThreatLab from '../components/ThreatLab';
import AttackFeed from '../components/AttackFeed';
import { useUI } from '../i18n/UIContext';
import { useAuth } from '../auth/AuthContext';
import { LogOut } from 'lucide-react';

type TabType = 'setup' | 'branding' | 'llm' | 'rag' | 'rag-scanning' | 'tools' | 'security' | 'providers' | 'prompts' | 'threat-lab' | 'export';

const AdminConsole: React.FC = () => {
  const { t } = useUI();
  const { user, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<TabType>('setup');
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState(false);
  const [ragScanningResult, setRagScanningResult] = useState<any>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [showProviderKey, setShowProviderKey] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [guardrailProviders, setGuardrailProviders] = useState<GuardrailProviderInfo[]>([]);
  const [revealedSecrets, setRevealedSecrets] = useState<Record<string, boolean>>({});
  const [showMCPInstructions, setShowMCPInstructions] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [ragScanningNotificationCount, setRagScanningNotificationCount] = useState<number>(0);
  const [ragScanningProgress, setRagScanningProgress] = useState<{isScanning: boolean; current: number; total: number; filename?: string} | null>(null);
  const progressPollingRef = useRef<number | null>(null);
  const ragManagementRef = React.useRef<RagManagementRef>(null);

  // Export sections: safe defaults on, api_keys and project_ids off
  const [exportInclude, setExportInclude] = useState<Record<string, boolean>>({
    appearance: true,
    llm: true,
    security: true,
    rag_scanning: true,
    demo_prompts: true,
    tools: true,
    rag: true,
    api_keys: false,
    project_ids: false,
  });
  const [lastImportIncludes, setLastImportIncludes] = useState<string[] | null>(null);

  useEffect(() => {
    loadConfig();
    loadModels();
    loadRagScanningResult();
    loadProviders();
  }, []);

  const loadProviders = async () => {
    try {
      const { providers } = await apiService.getProviders();
      setProviders(providers);
    } catch (error) {
      console.error('Failed to load providers:', error);
    }
    try {
      const { providers: gprov } = await apiService.getGuardrailProviders();
      setGuardrailProviders(gprov);
    } catch (error) {
      console.error('Failed to load guardrail providers:', error);
    }
  };
 
  useEffect(() => {
    if (config) {
      applyTheme(config.theme);
    }
  }, [config?.theme]);

  const applyTheme = (theme?: string) => {
    const themes = ['blue', 'emerald', 'purple', 'amber'];
    const body = document.body;
    themes.forEach(t => body.classList.remove(`theme-${t}`));
    const key = theme && themes.includes(theme) ? theme : 'blue';
    body.classList.add(`theme-${key}`);
  };

  // Clear notification when user views the RAG scanning report
  useEffect(() => {
    if (activeTab === 'rag-scanning') {
      clearRagScanningNotification();
    }
  }, [activeTab]);

  // Reload models when switching to LLM tab (e.g. after saving LiteLLM key in Security)
  useEffect(() => {
    if (activeTab === 'llm') {
      loadModels();
    }
  }, [activeTab]);

  // Poll for RAG scanning progress
  useEffect(() => {
    let intervalId: number;
    
    const pollProgress = async () => {
      try {
        const progress = await apiService.getRagScanningProgress();
        setRagScanningProgress(progress);
        
        // If progress is null or scanning is complete, stop polling
        if (!progress || !progress.isScanning) {
          if (intervalId) {
            clearInterval(intervalId);
            intervalId = 0;
          }
          setRagScanningProgress(null);
        }
      } catch {
        // No progress available, clear it and stop polling
        setRagScanningProgress(null);
        if (intervalId) {
          clearInterval(intervalId);
          intervalId = 0;
        }
      }
    };

    // Start polling if RAG content scanning is enabled (regardless of current tab)
    if (config?.rag_content_scanning) {
      intervalId = setInterval(pollProgress, 1000); // Poll every second
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [config?.rag_content_scanning]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (progressPollingRef.current) {
        clearInterval(progressPollingRef.current);
        progressPollingRef.current = null;
      }
    };
  }, []);

  // Start polling immediately when upload begins
  const startProgressPolling = () => {
    // Clear any existing polling
    if (progressPollingRef.current) {
      clearInterval(progressPollingRef.current);
      progressPollingRef.current = null;
    }

    // Show progress immediately with a placeholder
    setRagScanningProgress({
      isScanning: true,
      current: 0,
      total: 1,
      filename: "Uploading..."
    });

    let hasStartedScanning = false;
    let consecutive404s = 0;

    const pollProgress = async () => {
      try {
        const progress = await apiService.getRagScanningProgress();
        setRagScanningProgress(progress);
        
        // Reset 404 counter on successful response
        consecutive404s = 0;
        
        // If we get progress data, scanning has started
        if (progress) {
          hasStartedScanning = true;
        }
        
        // If progress is null or scanning is complete, stop polling
        if (!progress || !progress.isScanning) {
          if (progressPollingRef.current) {
            clearInterval(progressPollingRef.current);
            progressPollingRef.current = null;
          }
          // Keep the progress bar visible for a moment to show completion
          if (progress && !progress.isScanning) {
            setTimeout(() => setRagScanningProgress(null), 2000);
          } else {
            setRagScanningProgress(null);
          }
        }
      } catch (error: any) {
        console.log('Progress polling error:', error?.message);
        
        // If we get a 404, check if scanning has started
        if (error?.message?.includes('404') || error?.message?.includes('Not Found') || error?.message?.includes('API request failed: Not Found')) {
          consecutive404s++;
          
          // If scanning has started and we get 404s, it means scanning is complete
          if (hasStartedScanning) {
            console.log('Stopping progress polling - scanning completed');
            if (progressPollingRef.current) {
              clearInterval(progressPollingRef.current);
              progressPollingRef.current = null;
            }
            setRagScanningProgress(null);
          } else {
            // If scanning hasn't started yet, keep polling but limit consecutive 404s
            console.log(`Scanning not started yet, 404 count: ${consecutive404s}`);
            if (consecutive404s >= 10) {
              console.log('Too many 404s before scanning started, stopping polling');
              if (progressPollingRef.current) {
                clearInterval(progressPollingRef.current);
                progressPollingRef.current = null;
              }
              setRagScanningProgress(null);
            }
          }
        }
        // For other errors, keep trying for a bit
      }
    };
    
    // Start polling immediately, then continue with interval
    pollProgress();
    
    // Set up interval polling
    progressPollingRef.current = setInterval(pollProgress, 1000);
    
    // Clear interval after 2 minutes to prevent infinite polling
    setTimeout(() => {
      if (progressPollingRef.current) {
        clearInterval(progressPollingRef.current);
        progressPollingRef.current = null;
      }
      setRagScanningProgress(null);
    }, 120000);
  };

  const loadModels = async () => {
    try {
      const modelsData = await apiService.getModels();
      setAvailableModels(modelsData.models);
    } catch (error) {
      console.error('Failed to load models:', error);
      // Fallback to hardcoded models if API fails
      setAvailableModels([
        "gpt-5",
        "gpt-5-mini", 
        "gpt-5-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4",
        "gpt-4-turbo",
        "gpt-3.5-turbo"
      ]);
    }
  };

  const loadRagScanningResult = async () => {
    try {
      const result = await apiService.getLastRagScanningResult();
      setRagScanningResult(result);
      
      // Set notification count based on blocked chunks
      if (result && result.blocked_chunks > 0) {
        setRagScanningNotificationCount(result.blocked_chunks);
      } else {
        setRagScanningNotificationCount(0);
      }
    } catch {
      // No result available yet, that's okay
      setRagScanningResult(null);
      setRagScanningNotificationCount(0);
    }
  };

  const clearRagScanningNotification = () => {
    setRagScanningNotificationCount(0);
  };

  const loadConfig = async () => {
    try {
      const configData = await apiService.getConfig();
      // Ensure rag_content_scanning has a default value if not present
      if (configData.rag_content_scanning === undefined) {
        configData.rag_content_scanning = false;
      }
      setConfig(configData);
    } catch (error) {
      console.error('Failed to load config:', error);
      setMessage({ type: 'error', text: 'Failed to load configuration' });
    }
  };

  const handleConfigUpdate = async (updates: Partial<AppConfigUpdate>) => {
    if (!config) return;

    try {
      // Send only the fields the caller actually changed. Backend uses
      // Pydantic's exclude_unset=True so absent fields stay as-is, and the
      // demo-safe lock's value-comparison check (commit e16e61c) needs the
      // diff to be minimal. The old enumeration pattern dropped any new
      // field that wasn't in the hardcoded list — silently broke the lock
      // toggle and the Providers-tab Enabled toggle for several commits.
      const payload: Partial<AppConfigUpdate> = { ...updates };
      // Legacy invariant: turning Lakera off also turns RAG scanning off.
      if (updates.lakera_enabled === false) {
        payload.rag_content_scanning = false;
      }

      await apiService.updateConfig(payload);
      // Refresh everything that derives from AppConfig: the config snapshot
      // itself, model list (depends on active LLM provider), and the
      // provider catalogs (their `enabled`/`is_active` flags come from
      // backend's augment of disabled_providers + active_id).
      await Promise.all([loadConfig(), loadModels(), loadProviders()]);
      setMessage({ type: 'success', text: 'Configuration updated successfully' });
    } catch (error: any) {
      console.error('Failed to update config:', error);
      // Try to surface 403 (locked) and 400 (validation) details from backend
      const detail = error?.message || error?.detail || 'Failed to update configuration';
      setMessage({ type: 'error', text: String(detail) });
    }
  };

  const handleExport = async () => {
    setIsExporting(true);
    setMessage(null);
    try {
      const include = Object.entries(exportInclude)
        .filter(([, checked]) => checked)
        .map(([key]) => key);
      const blob = await apiService.exportConfig(include.length > 0 ? include : undefined);
      const url = window.URL.createObjectURL(blob);
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const defaultFilename = `agentic_demo_config_${timestamp}.zip`;
      const a = document.createElement('a');
      a.href = url;
      a.download = defaultFilename;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      setMessage({ type: 'success', text: 'Configuration exported successfully' });
    } catch (error) {
      console.error('Export failed:', error);
      setMessage({ type: 'error', text: 'Failed to export configuration' });
    } finally {
      setIsExporting(false);
    }
  };

  const handleImport = async (file: File) => {
    setIsImporting(true);
    setMessage(null);
    setLastImportIncludes(null);
    try {
      const result = await apiService.importConfig(file);
      await loadConfig();
      await loadModels();
      if (result.metadata?.includes?.length) {
        setLastImportIncludes(result.metadata.includes);
        const labels: Record<string, string> = {
          appearance: 'Appearance',
          llm: 'LLM',
          security: 'Security',
          rag_scanning: 'RAG scanning',
          demo_prompts: 'Demo prompts',
          tools: 'Tools',
          rag: 'RAG',
          api_keys: 'API keys',
          project_ids: 'Project IDs',
        };
        const names = result.metadata.includes.map((s: string) => labels[s] || s);
        setMessage({ type: 'success', text: `Imported: ${names.join(', ')}` });
      } else {
        setMessage({ type: 'success', text: 'Configuration imported successfully' });
      }
    } catch (error) {
      console.error('Import failed:', error);
      setMessage({ type: 'error', text: 'Failed to import configuration' });
    } finally {
      setIsImporting(false);
    }
  };

  const tabs: { id: TabType; label: string; notificationCount?: number }[] = [
    { id: 'setup', label: t('tabSetup') },
    { id: 'branding', label: t('tabBranding') },
    { id: 'llm', label: t('tabLLM') },
    { id: 'rag', label: t('tabRag') },
    { id: 'rag-scanning', label: t('tabRagScanning'), ...(ragScanningNotificationCount > 0 && { notificationCount: ragScanningNotificationCount }) },
    { id: 'tools', label: t('tabTools') },
    { id: 'security', label: t('tabSecurity') },
    { id: 'providers', label: 'Providers' },
    { id: 'prompts', label: t('tabPrompts') },
    { id: 'threat-lab', label: 'Threat Lab' },
    { id: 'export', label: t('tabExport') },
  ];

  if (!config) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="admin-page min-h-screen bg-gray-50 dark:bg-slate-900">
      <AttackFeed />
      {/* Header */}
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-200 dark:border-slate-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-4">
              <Link
                to="/"
                className="flex items-center space-x-2 text-gray-600 dark:text-slate-300 hover:text-gray-900 dark:hover:text-white"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>{t('backToDemo')}</span>
              </Link>
            </div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-slate-100">{t('adminConsole')}</h1>
            <div className="flex items-center gap-3">
              <UIToggles />
              {user && (
                <div className="flex items-center gap-2 pl-3 border-l border-gray-200 dark:border-slate-600">
                  <span className="text-xs text-gray-500 dark:text-slate-400">{user}</span>
                  <button
                    onClick={async () => { await logout(); window.location.href = '/login'; }}
                    title="Log out"
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700"
                  >
                    <LogOut className="w-3.5 h-3.5" /> Log out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Message */}
      {message && (
        <div className={`max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-4`}>
          <div className={`p-4 rounded-lg ${
            message.type === 'success' 
              ? 'bg-green-100 text-green-800 border border-green-200' 
              : 'bg-red-100 text-red-800 border border-red-200'
          }`}>
            {message.text}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
        <div className="border-b border-gray-200 dark:border-slate-700">
          <nav className="-mb-px flex space-x-8 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-2 px-1 border-b-2 font-medium text-sm relative whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                    : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 hover:border-gray-300 dark:hover:border-slate-600'
                }`}
              >
                <span className="flex items-center space-x-2">
                  <span>{tab.label}</span>
                  {tab.notificationCount !== undefined && tab.notificationCount > 0 && (
                    <span className="bg-red-500 text-white text-xs rounded-full h-5 w-5 flex items-center justify-center font-bold">
                      {tab.notificationCount}
                    </span>
                  )}
                </span>
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="mt-8">
          {/* Provider Config Lock — visible across all tabs; toggle always
              available so the operator can lock before customer demo and
              unlock when the demo ends. */}
          {(activeTab === 'llm' || activeTab === 'security') && config && (
            config.provider_config_locked ? (
              <div className="mb-4 bg-amber-50 border border-amber-300 rounded-lg p-3 flex items-center justify-between">
                <div>
                  <strong className="text-amber-900">🔒 Provider config locked</strong>
                  <p className="text-xs text-amber-800 mt-0.5">Read-only mode active. Provider keys, model, and active provider selection cannot be changed. Click Unlock to enable edits.</p>
                </div>
                <button
                  onClick={() => handleConfigUpdate({ provider_config_locked: false })}
                  className="ml-4 px-3 py-1.5 rounded text-sm bg-amber-600 text-white hover:bg-amber-700 whitespace-nowrap"
                >
                  🔓 Unlock
                </button>
              </div>
            ) : (
              <div className="mb-4 bg-gray-50 border border-gray-200 rounded p-2 flex items-center justify-between text-xs">
                <span className="text-gray-600">🔓 Provider config editable</span>
                <button
                  onClick={() => {
                    if (window.confirm('Lock provider config to read-only?\n\nUseful before a customer demo to prevent accidental key/provider changes during the session.\n\nYou can unlock at any time via this same banner.')) {
                      handleConfigUpdate({ provider_config_locked: true });
                    }
                  }}
                  className="px-2 py-1 rounded bg-gray-200 hover:bg-gray-300 text-gray-700"
                >
                  🔒 Lock for demo
                </button>
              </div>
            )
          )}
          {activeTab === 'setup' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900">Setup Instructions</h2>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
                <h3 className="text-md font-medium text-blue-900 mb-4">🚀 Welcome to Agentic Demo!</h3>
                <p className="text-sm text-blue-800 mb-4">
                  Follow these steps to get your demo up and running. Complete them in order for the best experience.
                </p>
                
                <div className="space-y-4">
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">1</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Configure API Keys</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>Security</strong> tab and enter either your OpenAI API key or LiteLLM API key (master or virtual). Add a Lakera API key if you want moderation enabled. In the demo, open the prompt interface and ask something simple like &quot;How is your day&quot; to test the keys.</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">2</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Customize Your Branding</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>Branding</strong> tab to set your business tagline, logo or business name, and hero image. Example images can be found in the fakecompanies directory.  In an IDE, right click on the image in that directory and select "Copy Relative Path" to get the URL.   </p>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">3</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Configure LLM Settings</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>LLM</strong> tab to select your OpenAI model, add your system prompt and adjust temperature settings.</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">4</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Add Content to RAG</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>RAG</strong> tab to upload documents or generate AI content for your knowledge base.  Again there are a few example documents in the fakecompanies directory like customer lists and financial transactions. </p>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">5</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Add Demo Prompts</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>Demo Prompts</strong> tab to create curated prompts for consistent demos.<br></br>Examples:<br></br>"How do I make a bomb"<br></br>"What is Taylor's credit card number?"</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-6 h-6 bg-blue-600 text-white rounded-full flex items-center justify-center text-sm font-medium">6</div>
                    <div>
                      <h4 className="font-medium text-blue-900">Configure Tools (Optional)</h4>
                      <p className="text-sm text-blue-800">Go to the <strong>Tools</strong> tab to add custom MCP tools for enhanced functionality.</p>
                    </div>
                  </div>
                </div>
                
                <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <button
                    onClick={() => setShowMCPInstructions(!showMCPInstructions)}
                    className="flex items-center justify-between w-full text-left"
                  >
                    <h4 className="font-medium text-yellow-900">🔧 Advanced: MCP Tools Setup</h4>
                    {showMCPInstructions ? (
                      <ChevronDown className="w-4 h-4 text-yellow-700" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-yellow-700" />
                    )}
                  </button>
                  
                  {showMCPInstructions && (
                    <div className="mt-4 space-y-4">
                      <p className="text-sm text-yellow-800">
                        For advanced functionality, you can add MCP (Model Context Protocol) tools using ToolHive.
                      </p>
                      
                      <div className="space-y-4">
                        <div>
                          <h5 className="font-medium text-yellow-900 mb-2">Step 1: Install ToolHive</h5>
                          <p className="text-sm text-yellow-800 mb-2">
                            Download and install ToolHive from the official documentation:
                          </p>
                          <a 
                            href="https://docs.stacklok.com/toolhive/guides-ui/install" 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="inline-flex items-center text-sm text-blue-600 hover:text-blue-800 underline"
                          >
                            📖 ToolHive Installation Guide
                          </a>
                        </div>
                        
                        <div>
                          <h5 className="font-medium text-yellow-900 mb-2">Step 2: Add Fetch MCP Server</h5>
                          <ol className="text-sm text-yellow-800 space-y-1 ml-4 list-decimal">
                            <li>Open ToolHive and go to the <strong>Registry</strong> tab</li>
                            <li>Search for "Fetch" in the default registry</li>
                            <li>Add it to your local servers</li>
                            <li>Go to <strong>MCP Servers</strong> tab and copy the endpoint URL</li>
                            <li>In this demo's <strong>Tools</strong> tab, add a new tool with that endpoint</li>
                            <li>Click <strong>Test Tool</strong> to verify it shows available tools</li>
                            <li>Try a prompt like "Tell me more about https://checkpoint.com" to see if the tool works. If so, save that prompt for the demo</li>
                          </ol>
                        </div>
                        
                        <div>
                          <h5 className="font-medium text-yellow-900 mb-2">Step 3: Add Filesystem MCP Server</h5>
                          <ol className="text-sm text-yellow-800 space-y-1 ml-4 list-decimal">
                            <li>Add "Filesystem" from the default registry in ToolHive</li>
                            <li>Configure the server with these settings:</li>
                            <li className="ml-4">• <strong>Host path:</strong> Full path to your documents folder (e.g., "/Users/steve/Documents/mcpdemodocs")</li>
                            <li className="ml-4">• <strong>Container path:</strong> "/projects"</li>
                            <li>Add the endpoint URL as a new tool in this demo</li>
                            <li>Create a file like "hello.txt" in your documents folder</li>
                            <li>Try a prompt like "What is in the file in the /projects directory hello.txt" to test the server</li>
                          </ol>
                        </div>
                        
                        <div className="p-3 bg-yellow-100 rounded border-l-4 border-yellow-400">
                          <p className="text-sm text-yellow-800">
                            <strong>💡 Pro Tip:</strong> Add a malicious system prompt to the bottom of your test file to see Lakera Guard detect and block it!
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                
                <div className="mt-6 p-4 bg-blue-100 rounded-lg">
                  <h4 className="font-medium text-blue-900 mb-2">💡 Pro Tips:</h4>
                  <ul className="text-sm text-blue-800 space-y-1">
                    <li>• Start with basic configuration, then add advanced features</li>
                    <li>• Test your setup by going to the main demo page</li>
                    <li>• Use the Export/Import feature to save your configuration</li>
                    <li>• Check the browser console for any errors</li>
                  </ul>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'branding' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900">Branding Configuration</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Business Name
                  </label>
                  <input
                    type="text"
                    value={config.business_name || ''}
                    onChange={(e) => handleConfigUpdate({ business_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Tagline
                  </label>
                  <input
                    type="text"
                    value={config.tagline || ''}
                    onChange={(e) => handleConfigUpdate({ tagline: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Hero Text
                  </label>
                  <textarea
                    value={config.hero_text || ''}
                    onChange={(e) => handleConfigUpdate({ hero_text: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Logo URL
                  </label>
                  <input
                    type="url"
                    value={config.logo_url || ''}
                    onChange={(e) => handleConfigUpdate({ logo_url: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Hero Image URL
                  </label>
                  <input
                    type="url"
                    value={config.hero_image_url || ''}
                    onChange={(e) => handleConfigUpdate({ hero_image_url: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Theme
                  </label>
                  <select
                    value={config.theme || 'blue'}
                    onChange={(e) => handleConfigUpdate({ theme: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    <option value="blue">Blue (Default Tech)</option>
                    <option value="emerald">Emerald (FinTech / Green)</option>
                    <option value="purple">Purple (SaaS)</option>
                    <option value="amber">Amber (Enterprise)</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    Changes primary accent colors and font to better match your prospect&apos;s branding.
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'llm' && (
            <fieldset disabled={!!config?.provider_config_locked} className={`space-y-6 border-0 p-0 m-0 min-w-0 ${config?.provider_config_locked ? 'opacity-70' : ''}`}>
              <h2 className="text-lg font-semibold text-gray-900">LLM Configuration</h2>

              {/* Provider + key + (optional) base URL — moved here from Security so
                  provider + model live together. */}
              {(() => {
                const activeProviderId = config.llm_provider || (config.use_litellm ? 'litellm_proxy' : 'openai');
                const activeProvider = providers.find((p) => p.id === activeProviderId);
                const keyField = activeProvider?.key_field as keyof AppConfig | null | undefined;
                const baseField = activeProvider?.base_url_field as keyof AppConfig | null | undefined;
                const keyValue = keyField ? ((config as any)[keyField] as string | undefined) : undefined;
                const baseValue = baseField ? ((config as any)[baseField] as string | undefined) : undefined;
                return (
                  <div className="space-y-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        LLM Provider
                      </label>
                      <select
                        value={activeProviderId}
                        onChange={(e) => handleConfigUpdate({ llm_provider: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      >
                        {providers.length === 0 ? (
                          <option value={activeProviderId}>{activeProviderId}</option>
                        ) : (
                          providers.map((p) => (
                            <option key={p.id} value={p.id}>{p.display_name}</option>
                          ))
                        )}
                      </select>
                      <p className="text-xs text-gray-500 mt-1">
                        Each provider stores its own key, so switching back and forth doesn&apos;t require re-entering credentials.
                      </p>
                    </div>

                    {baseField && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {activeProviderId === 'ollama' ? 'Ollama base URL' : 'LiteLLM base URL'}
                        </label>
                        <input
                          type="text"
                          value={baseValue || activeProvider?.default_base_url || ''}
                          onChange={(e) => handleConfigUpdate({ [baseField]: e.target.value } as any)}
                          placeholder={activeProvider?.default_base_url || ''}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                      </div>
                    )}

                    {activeProviderId === 'portkey' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Portkey virtual key (optional)
                        </label>
                        <input
                          type="text"
                          value={config.portkey_virtual_key || ''}
                          onChange={(e) => handleConfigUpdate({ portkey_virtual_key: e.target.value })}
                          placeholder="vk-..."
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                        <p className="text-xs text-gray-500 mt-1">
                          Portkey&apos;s virtual key abstracts the upstream provider (OpenAI/Anthropic/etc.). Leave empty if your Portkey config routes by other means.
                        </p>
                      </div>
                    )}

                    {keyField && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          {activeProvider?.display_name} API key
                          {!activeProvider?.needs_key && (
                            <span className="ml-2 text-xs text-gray-500">(optional)</span>
                          )}
                        </label>
                        <div className="relative">
                          <input
                            type={showProviderKey ? 'text' : 'password'}
                            value={keyValue || ''}
                            onChange={(e) => handleConfigUpdate({ [keyField]: e.target.value } as any)}
                            placeholder={
                              activeProviderId === 'openai' ? 'sk-...' :
                              activeProviderId === 'anthropic' ? 'sk-ant-...' :
                              activeProviderId === 'google' ? 'AIza...' :
                              activeProviderId === 'litellm_proxy' ? 'sk-... (master or virtual) or leave empty' :
                              activeProviderId === 'openrouter' ? 'sk-or-...' :
                              'API key'
                            }
                            className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                          />
                          <button
                            type="button"
                            onClick={() => setShowProviderKey(!showProviderKey)}
                            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
                          >
                            {showProviderKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>
                    )}

                    {!keyField && !baseField && (
                      <p className="text-xs text-gray-500">
                        This provider doesn&apos;t require any extra credentials in this app.
                      </p>
                    )}
                  </div>
                );
              })()}

              {config.openai_model && availableModels.length > 0 && !availableModels.includes(config.openai_model) && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                  Current model may not be available for this provider. Select a model below and save.
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Model
                  </label>
                  <select
                    value={config.openai_model}
                    onChange={(e) => handleConfigUpdate({ openai_model: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    {config.openai_model && !availableModels.includes(config.openai_model) && (
                      <option key={config.openai_model} value={config.openai_model}>
                        {config.openai_model} (not available)
                      </option>
                    )}
                    {availableModels.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Temperature (0-10)
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="10"
                    value={config.temperature}
                    onChange={(e) => handleConfigUpdate({ temperature: parseInt(e.target.value) })}
                    className="w-full"
                  />
                  <span className="text-sm text-gray-500">{config.temperature}</span>
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    System Prompt
                  </label>
                  <textarea
                    value={config.system_prompt || ''}
                    onChange={(e) => handleConfigUpdate({ system_prompt: e.target.value })}
                    rows={4}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
              </div>
            </fieldset>
          )}

          {activeTab === 'rag' && (
            <div className="space-y-6">
              {/* RAG Scanning Progress Indicator - Only show on RAG tab */}
              {ragScanningProgress && ragScanningProgress.isScanning && (
                <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center space-x-3">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-blue-900">
                        Scanning content for security threats...
                      </div>
                      <div className="text-xs text-blue-700 mt-1">
                        {ragScanningProgress.filename && `File: ${ragScanningProgress.filename}`}
                      </div>
                      <div className="mt-2">
                        <div className="flex items-center justify-between text-xs text-blue-700 mb-1">
                          <span>Progress</span>
                          <span>{ragScanningProgress.current} / {ragScanningProgress.total} chunks</span>
                        </div>
                        <div className="w-full bg-blue-200 rounded-full h-2">
                          <div 
                            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${(ragScanningProgress.current / ragScanningProgress.total) * 100}%` }}
                          ></div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <h2 className="text-lg font-semibold text-gray-900">RAG Configuration</h2>
              <div className="space-y-6">
                <div>
                  <h3 className="text-md font-medium text-gray-800 mb-4">Upload Documents</h3>
                  <UploadDropzone 
                    onUploadStart={() => {
                      // Start progress polling immediately when upload begins
                      startProgressPolling();
                    }}
                    onUploadComplete={() => {
                      setMessage({ type: 'success', text: 'Document uploaded successfully' });
                      ragManagementRef.current?.refresh();
                      // Refresh RAG scanning results after upload
                      setTimeout(() => loadRagScanningResult(), 1000);
                    }} 
                  />
                </div>
                <div>
                  <h3 className="text-md font-medium text-gray-800 mb-4">Generate AI Content</h3>
                  <div className="bg-gray-50 p-4 rounded-lg">
                    <p className="text-sm text-gray-600 mb-4">
                      Generate industry-specific content using AI and add it to your RAG system.
                    </p>
                    <button 
                      onClick={() => setIsGenerateModalOpen(true)}
                      className="bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700"
                    >
                      Generate Content
                    </button>
                  </div>
                </div>
                <div>
                  <RagManagement 
                    ref={ragManagementRef}
                    onUploadStart={() => {
                      // Start progress polling immediately when upload begins
                      startProgressPolling();
                    }}
                    onUploadComplete={() => {
                      setMessage({ type: 'success', text: 'Document uploaded successfully' });
                      ragManagementRef.current?.refresh();
                      // Refresh RAG scanning results after upload
                      setTimeout(() => loadRagScanningResult(), 1000);
                    }}
                    onGenerateComplete={() => setMessage({ type: 'success', text: 'Content generated successfully' })}
                  />
                </div>
              </div>
            </div>
          )}

          {activeTab === 'rag-scanning' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900">RAG Content Scanning Report</h2>
              
              {!config.rag_content_scanning ? (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
                  <div className="flex items-center space-x-3">
                    <div className="text-yellow-600">⚠️</div>
                    <div>
                      <h3 className="text-sm font-medium text-yellow-900">RAG Content Scanning Disabled</h3>
                      <p className="text-sm text-yellow-800 mt-1">
                        RAG content scanning is currently disabled. Enable it in the Security tab to scan uploaded documents for malicious content.
                      </p>
                    </div>
                  </div>
                </div>
              ) : !ragScanningResult ? (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
                  <div className="flex items-center space-x-3">
                    <div className="text-blue-600">ℹ️</div>
                    <div>
                      <h3 className="text-sm font-medium text-blue-900">No Scanning Results Yet</h3>
                      <p className="text-sm text-blue-800 mt-1">
                        Upload a document in the RAG tab to see content scanning results here. Any blocked content will be reported with detailed information.
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className={`p-6 rounded-lg border ${
                  ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks === 0
                    ? 'bg-red-50 border-red-200' // All content blocked
                    : ragScanningResult.blocked_chunks > 0
                    ? 'bg-yellow-50 border-yellow-200' // Some content blocked
                    : 'bg-green-50 border-green-200' // All content safe
                }`}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center space-x-3">
                      <h3 className={`text-lg font-medium ${
                        ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks === 0
                          ? 'text-red-900' // All content blocked
                          : ragScanningResult.blocked_chunks > 0
                          ? 'text-yellow-900' // Some content blocked
                          : 'text-green-900' // All content safe
                      }`}>
                        Scanning Results
                      </h3>
                      {ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks === 0 && (
                        <span className="bg-red-200 text-red-800 text-sm px-3 py-1 rounded-full font-medium">
                          ALL CONTENT BLOCKED
                        </span>
                      )}
                      {ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks > 0 && (
                        <span className="bg-yellow-200 text-yellow-800 text-sm px-3 py-1 rounded-full font-medium">
                          PARTIAL BLOCK
                        </span>
                      )}
                      {ragScanningResult.blocked_chunks === 0 && (
                        <span className="bg-green-200 text-green-800 text-sm px-3 py-1 rounded-full font-medium">
                          ALL CONTENT SAFE
                        </span>
                      )}
                    </div>
                    <button
                      onClick={loadRagScanningResult}
                      className={`text-sm px-4 py-2 rounded-lg font-medium ${
                        ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks === 0
                          ? 'bg-red-100 text-red-700 hover:bg-red-200'
                          : ragScanningResult.blocked_chunks > 0
                          ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
                          : 'bg-green-100 text-green-700 hover:bg-green-200'
                      }`}
                    >
                      Refresh Results
                    </button>
                  </div>
                  
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="bg-white p-4 rounded-lg border">
                        <div className="flex items-center space-x-2">
                          <span className="text-green-600 text-lg">✅</span>
                          <div>
                            <div className="text-2xl font-bold text-green-600">{ragScanningResult.safe_chunks}</div>
                            <div className="text-sm text-gray-600">Safe Chunks</div>
                          </div>
                        </div>
                      </div>
                      <div className="bg-white p-4 rounded-lg border">
                        <div className="flex items-center space-x-2">
                          <span className="text-red-600 text-lg">🚫</span>
                          <div>
                            <div className="text-2xl font-bold text-red-600">{ragScanningResult.blocked_chunks}</div>
                            <div className="text-sm text-gray-600">Blocked Chunks</div>
                          </div>
                        </div>
                      </div>
                      <div className="bg-white p-4 rounded-lg border">
                        <div className="flex items-center space-x-2">
                          <span className="text-blue-600 text-lg">📄</span>
                          <div>
                            <div className="text-sm font-medium text-gray-900 truncate">{ragScanningResult.filename}</div>
                            <div className="text-sm text-gray-600">Scanned File</div>
                          </div>
                        </div>
                      </div>
                    </div>
                    
                    {ragScanningResult.blocked_chunks > 0 && ragScanningResult.safe_chunks === 0 && (
                      <div className="p-4 bg-red-100 border border-red-300 rounded-lg">
                        <div className="flex items-start space-x-3">
                          <span className="text-red-600 text-lg">⚠️</span>
                          <div>
                            <h4 className="font-medium text-red-900">Security Alert</h4>
                            <p className="text-sm text-red-800 mt-1">
                              All content in this file was blocked by security scanning. No content was added to the RAG database. 
                              Check the detailed results below for specific reasons why each chunk was blocked.
                            </p>
                          </div>
                        </div>
                      </div>
                    )}
                    
                    {ragScanningResult.results && ragScanningResult.results.length > 0 && (
                      <div className="space-y-3">
                        <h4 className="text-md font-medium text-gray-900">Detailed Chunk Analysis</h4>
                        <div className="space-y-2 max-h-96 overflow-y-auto">
                          {ragScanningResult.results.map((result: any, index: number) => (
                            <div key={index} className={`p-4 rounded-lg border ${
                              result.is_safe 
                                ? 'bg-green-50 border-green-200' 
                                : 'bg-red-50 border-red-200'
                            }`}>
                              <div className="flex items-start justify-between mb-2">
                                <div className="flex items-center space-x-2">
                                  <span className="font-medium text-gray-900">Chunk {result.chunk_index}</span>
                                  <span className={`text-xs px-2 py-1 rounded-full font-medium ${
                                    result.is_safe 
                                      ? 'bg-green-200 text-green-800' 
                                      : 'bg-red-200 text-red-800'
                                  }`}>
                                    {result.is_safe ? '✅ Safe' : '🚫 Blocked'}
                                  </span>
                                </div>
                                {!result.is_safe && result.reason && (
                                  <span className="text-xs text-red-600 font-medium">
                                    Reason: {result.reason}
                                  </span>
                                )}
                              </div>
                              <div className="text-sm text-gray-700 bg-white p-3 rounded border">
                                {result.chunk_text}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'tools' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900">Tool Management</h2>
              <ToolManager />
            </div>
          )}

          {activeTab === 'security' && (
            <fieldset disabled={!!config?.provider_config_locked} className={`space-y-6 border-0 p-0 m-0 min-w-0 ${config?.provider_config_locked ? 'opacity-70' : ''}`}>
              <h2 className="text-lg font-semibold text-gray-900">Security Configuration</h2>
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-4">
                    <div className="space-y-4">
                      <div className="flex items-center space-x-3">
                        <button
                          type="button"
                          onClick={() => handleConfigUpdate({ lakera_enabled: !config.lakera_enabled })}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                            config.lakera_enabled ? 'bg-primary-600' : 'bg-gray-200'
                          }`}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                              config.lakera_enabled ? 'translate-x-6' : 'translate-x-1'
                            }`}
                          />
                        </button>
                        <label className="text-sm font-medium text-gray-700">
                          Enable Lakera Guard
                        </label>
                      </div>
                      
                      {config.lakera_enabled && (
                        <div className="ml-8 p-4 bg-gray-50 rounded-lg border">
                          <h4 className="text-sm font-medium text-gray-700 mb-3">Security Options</h4>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Blocking Mode Toggle */}
                            <div className="flex items-center space-x-3">
                              <button
                                type="button"
                                onClick={() => handleConfigUpdate({ lakera_blocking_mode: !config.lakera_blocking_mode })}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                                  config.lakera_blocking_mode ? 'bg-red-600' : 'bg-gray-200'
                                }`}
                              >
                                <span
                                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                    config.lakera_blocking_mode ? 'translate-x-6' : 'translate-x-1'
                                  }`}
                                />
                              </button>
                              <div>
                                <label className="text-sm font-medium text-gray-700">
                                  Blocking Mode
                                </label>
                                <p className="text-xs text-gray-500">
                                  Block flagged content instead of just logging
                                </p>
                              </div>
                            </div>
                            
                            {/* RAG Content Scanning Toggle */}
                            <div className="flex items-center space-x-3">
                              <button
                                type="button"
                                onClick={() => handleConfigUpdate({ rag_content_scanning: !config.rag_content_scanning })}
                                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                                  config.rag_content_scanning ? 'bg-primary-600' : 'bg-gray-200'
                                }`}
                              >
                                <span
                                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                    config.rag_content_scanning ? 'translate-x-6' : 'translate-x-1'
                                  }`}
                                />
                              </button>
                              <div>
                                <label className="text-sm font-medium text-gray-700">
                                  RAG Content Scanning
                                </label>
                                <p className="text-xs text-gray-500">
                                  Scan document chunks during ingestion
                                </p>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                      
                      {config.rag_content_scanning && (
                        <div className="space-y-2">
                          <label className="block text-sm font-medium text-gray-700">
                            RAG Scanning Project ID
                          </label>
                          <input
                            type="text"
                            value={config.rag_lakera_project_id || ''}
                            onChange={(e) => handleConfigUpdate({ rag_lakera_project_id: e.target.value })}
                            placeholder="project-8541012967"
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                          />
                          <p className="text-xs text-gray-500">
                            Separate project ID for RAG content scanning to keep it isolated from chat interface scanning.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  {config.lakera_enabled && (
                    <div className="text-xs text-gray-500 max-w-xs">
                      {config.lakera_blocking_mode 
                        ? "🚫 Blocking mode enabled - flagged content will be blocked" 
                        : "📝 Logging mode - flagged content will be logged but allowed"}
                    </div>
                  )}
                </div>
                
                <p className="text-xs text-gray-500 italic">
                  LLM provider, API key, and base URL moved to the <strong>LLM</strong> tab so they sit next to the model picker. This tab now covers guardrails and webhooks only.
                </p>
                {config.llm_provider === 'litellm_proxy' && config.lakera_enabled && (
                  <div className="space-y-3">
                    <p className="text-xs text-gray-600">
                      In LiteLLM mode, the app selects a guardrail name based on Lakera blocking mode.
                      These names should match entries in <code className="text-xs bg-gray-100 px-1 rounded">litellm/config.yaml</code>.
                    </p>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        LiteLLM guardrail name (blocking)
                      </label>
                      <input
                        type="text"
                        value={config.litellm_guardrail_name ?? ''}
                        onChange={(e) => handleConfigUpdate({ litellm_guardrail_name: e.target.value })}
                        placeholder="lakera-guard-block"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        LiteLLM guardrail name (monitor)
                      </label>
                      <input
                        type="text"
                        value={config.litellm_guardrail_monitor_name ?? ''}
                        onChange={(e) =>
                          handleConfigUpdate({ litellm_guardrail_monitor_name: e.target.value })
                        }
                        placeholder="lakera-guard-monitor"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                  </div>
                )}
                {/* Guardrail provider selector + per-provider config */}
                {(() => {
                  const activeGuardrailId = config.guardrail_provider || 'lakera';
                  const activeProvider = guardrailProviders.find((p) => p.id === activeGuardrailId);
                  return (
                    <div className="space-y-4 pt-4 border-t border-gray-200">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Guardrail provider
                        </label>
                        <select
                          value={activeGuardrailId}
                          onChange={(e) => handleConfigUpdate({ guardrail_provider: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                        >
                          {guardrailProviders.length === 0 ? (
                            <option value={activeGuardrailId}>{activeGuardrailId}</option>
                          ) : (
                            guardrailProviders.map((p) => (
                              <option key={p.id} value={p.id}>{p.display_name}</option>
                            ))
                          )}
                        </select>
                        {activeProvider?.summary && (
                          <p className="text-xs text-gray-500 mt-1">
                            {activeProvider.summary}
                            {activeProvider.docs_url && (
                              <>
                                {' · '}
                                <a href={activeProvider.docs_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
                                  docs ↗
                                </a>
                              </>
                            )}
                          </p>
                        )}
                      </div>

                      {/* Per-provider fields driven by /api/guardrail-providers catalog */}
                      {activeProvider?.fields.map((field) => {
                        const key = field.name as keyof AppConfig;
                        const value = (config[key] as string | undefined) || '';
                        const isSecret = field.type === 'password';
                        const revealed = revealedSecrets[field.name] ?? false;
                        return (
                          <div key={field.name}>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                              {field.label}
                            </label>
                            <div className="relative">
                              <input
                                type={isSecret && !revealed ? 'password' : 'text'}
                                value={value}
                                onChange={(e) => handleConfigUpdate({ [field.name]: e.target.value } as any)}
                                placeholder={field.placeholder || ''}
                                className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                              />
                              {isSecret && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setRevealedSecrets((prev) => ({ ...prev, [field.name]: !prev[field.name] }))
                                  }
                                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
                                >
                                  {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}

                      {activeProvider && activeProvider.fields.length === 0 && (
                        <p className="text-xs text-gray-500 italic">
                          This provider reuses credentials configured above (no extra fields needed).
                        </p>
                      )}
                    </div>
                  );
                })()}
              </div>
            </fieldset>
          )}

          {activeTab === 'providers' && (
            <ProvidersTab
              providers={providers}
              guardrailProviders={guardrailProviders}
              config={config}
              onConfigUpdate={handleConfigUpdate}
              onActivate={(kind, id) => handleConfigUpdate(
                kind === 'llm' ? { llm_provider: id } : { guardrail_provider: id }
              )}
            />
          )}

          {activeTab === 'prompts' && (
            <div className="space-y-6">
              <DemoPromptManager />
            </div>
          )}

          {activeTab === 'threat-lab' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-slate-100">Threat Lab</h2>
              <p className="text-sm text-gray-600 dark:text-slate-400">
                Audit log, side-by-side guardrail compare, OWASP LLM Top 10 playbook runner,
                and replayable recordings.
              </p>
              <ThreatLab />
            </div>
          )}

          {activeTab === 'export' && (
            <div className="space-y-6">
              <h2 className="text-lg font-semibold text-gray-900">Export/Import Configuration</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-gray-50 p-6 rounded-lg">
                  <h3 className="text-md font-medium text-gray-800 mb-4">Export Configuration</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    Choose what to include. By default, API keys and project IDs are excluded so the file is safe to share for demo setup.
                  </p>
                  <div className="space-y-2 mb-4">
                    {[
                      { key: 'appearance', label: 'Appearance (branding, hero, logo)' },
                      { key: 'llm', label: 'LLM settings (model, temperature, system prompt)' },
                      { key: 'security', label: 'Security toggles (Lakera enabled/blocking)' },
                      { key: 'rag_scanning', label: 'RAG scanning (toggle only)' },
                      { key: 'demo_prompts', label: 'Demo prompts' },
                      { key: 'tools', label: 'Tools' },
                      { key: 'rag', label: 'RAG sources + vector store' },
                    ].map(({ key, label }) => (
                      <label key={key} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={exportInclude[key] ?? false}
                          onChange={(e) => setExportInclude((prev) => ({ ...prev, [key]: e.target.checked }))}
                          className="h-4 w-4 text-primary-600 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-700">{label}</span>
                      </label>
                    ))}
                    <div className="border-t border-gray-200 pt-2 mt-2 space-y-2">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={exportInclude.api_keys ?? false}
                          onChange={(e) => setExportInclude((prev) => ({ ...prev, api_keys: e.target.checked }))}
                          className="h-4 w-4 text-primary-600 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-700">Include API keys</span>
                      </label>
                      <p className="text-xs text-amber-700 bg-amber-50 px-2 py-1 rounded">Only for your own backup; do not share.</p>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={exportInclude.project_ids ?? false}
                          onChange={(e) => setExportInclude((prev) => ({ ...prev, project_ids: e.target.checked }))}
                          className="h-4 w-4 text-primary-600 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-700">Include project IDs</span>
                      </label>
                      <p className="text-xs text-amber-700 bg-amber-50 px-2 py-1 rounded">Only for your own backup; do not share.</p>
                    </div>
                  </div>
                  <button
                    onClick={handleExport}
                    disabled={isExporting}
                    className="flex items-center space-x-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                  >
                    {isExporting ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>Exporting...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-4 h-4" />
                        <span>Export Config</span>
                      </>
                    )}
                  </button>
                </div>
                <div className="bg-gray-50 p-6 rounded-lg">
                  <h3 className="text-md font-medium text-gray-800 mb-4">Import Configuration</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    Upload a previously exported zip. Only the sections present in the file are applied; your API keys and project IDs are left unchanged unless the file included them.
                  </p>
                  <p className="text-xs text-gray-500 mb-4">
                    To get demo prompts, export from an environment that already has them (with &quot;Demo prompts&quot; checked), then import that file here. Zips from the old export format do not include demo prompts.
                  </p>
                  {lastImportIncludes && lastImportIncludes.length > 0 && (
                    <p className="text-sm text-gray-600 mb-4">
                      Last import applied: {lastImportIncludes.join(', ')}
                    </p>
                  )}
                  {isImporting ? (
                    <div className="flex items-center space-x-2 text-primary-600">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600"></div>
                      <span className="text-sm">Importing configuration...</span>
                    </div>
                  ) : (
                    <input
                      type="file"
                      accept=".zip"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleImport(file);
                        e.target.value = '';
                      }}
                      className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary-600 file:text-white hover:file:bg-primary-700"
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Generate Content Modal */}
      <GenerateContentModal
        isOpen={isGenerateModalOpen}
        onClose={() => setIsGenerateModalOpen(false)}
        onContentGenerated={() => {
          setMessage({ type: 'success', text: 'Content generated and ingested successfully' });
          setIsGenerateModalOpen(false);
          ragManagementRef.current?.refresh();
        }}
      />
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────
// Providers tab — unified provider management (LLM + Guardrail)
//
// Per row: status badge, active radio, enable/disable toggle. Edit of
// individual keys still lives on the LLM/Security tabs (link out) — we
// don't duplicate per-provider key forms here yet.
// ─────────────────────────────────────────────────────────────────

interface ProvidersTabProps {
  providers: (ProviderInfo & { enabled?: boolean; is_active?: boolean })[];
  guardrailProviders: (GuardrailProviderInfo & { enabled?: boolean; is_active?: boolean })[];
  config: AppConfig;
  onConfigUpdate: (updates: Partial<AppConfigUpdate>) => Promise<void>;
  onActivate: (kind: 'llm' | 'guardrail', id: string) => Promise<void>;
}

// Per-provider field schemas — single source of truth for the EditProviderModal.
// Adding a new provider requires extending PROVIDERS in backend/providers.py
// (or backend/guardrail_provider/) AND adding an entry here, since the
// modal renders inputs from this schema. Backend remains source of truth
// for what's valid; this just drives the form.
type ProviderFieldDef = {
  field: string;          // AppConfig column name
  label: string;
  type: 'text' | 'password';
  required?: boolean;
  placeholder?: string;
  help?: string;
};

const PROVIDER_FIELD_SCHEMAS: Record<string, ProviderFieldDef[]> = {
  // LLM providers
  openai: [{ field: 'openai_api_key', label: 'OpenAI API Key', type: 'password', required: true, placeholder: 'sk-...' }],
  anthropic: [{ field: 'anthropic_api_key', label: 'Anthropic API Key', type: 'password', required: true, placeholder: 'sk-ant-...' }],
  google: [{ field: 'google_api_key', label: 'Google AI API Key', type: 'password', required: true }],
  mistral: [{ field: 'mistral_api_key', label: 'Mistral API Key', type: 'password', required: true }],
  groq: [{ field: 'groq_api_key', label: 'Groq API Key', type: 'password', required: true }],
  together: [{ field: 'together_api_key', label: 'Together AI API Key', type: 'password', required: true }],
  openrouter: [{ field: 'openrouter_api_key', label: 'OpenRouter API Key', type: 'password', required: true }],
  ollama: [{ field: 'ollama_base_url', label: 'Ollama Base URL', type: 'text', placeholder: 'http://localhost:11434', help: 'No key needed — set the local Ollama server address' }],
  litellm_proxy: [
    { field: 'litellm_virtual_key', label: 'LiteLLM Virtual Key', type: 'password', required: true },
    { field: 'litellm_base_url', label: 'LiteLLM Base URL', type: 'text', required: true, placeholder: 'http://localhost:4000' },
    { field: 'litellm_guardrail_name', label: 'Guardrail Name (block mode)', type: 'text', help: 'Optional — name of LiteLLM guardrail used in blocking mode' },
    { field: 'litellm_guardrail_monitor_name', label: 'Guardrail Name (monitor mode)', type: 'text', help: 'Optional — name of LiteLLM guardrail used in monitor mode' },
  ],
  portkey: [
    { field: 'portkey_api_key', label: 'Portkey API Key', type: 'password', required: true },
    { field: 'portkey_virtual_key', label: 'Portkey Virtual Key', type: 'password' },
    { field: 'portkey_base_url', label: 'Portkey Base URL', type: 'text', placeholder: 'https://api.portkey.ai/v1' },
  ],
  // Guardrail providers
  lakera: [
    { field: 'lakera_api_key', label: 'Lakera API Key', type: 'password', required: true },
    { field: 'lakera_project_id', label: 'Lakera Project ID', type: 'text', required: true, placeholder: 'project-...' },
  ],
  openai_moderation: [
    { field: 'openai_api_key', label: 'OpenAI API Key (shared with LLM provider)', type: 'password', required: true, help: 'OpenAI Moderation reuses the OpenAI key from the LLM section — editing here updates both' },
  ],
  bedrock: [
    { field: 'bedrock_access_key_id', label: 'AWS Access Key ID', type: 'password', required: true },
    { field: 'bedrock_secret_access_key', label: 'AWS Secret Access Key', type: 'password', required: true },
    { field: 'bedrock_region', label: 'AWS Region', type: 'text', required: true, placeholder: 'us-east-1' },
    { field: 'bedrock_guardrail_id', label: 'Guardrail ID', type: 'text', required: true },
    { field: 'bedrock_guardrail_version', label: 'Guardrail Version', type: 'text', placeholder: 'DRAFT' },
  ],
  azure_content_safety: [
    { field: 'azure_content_safety_endpoint', label: 'Endpoint URL', type: 'text', required: true, placeholder: 'https://X.cognitiveservices.azure.com' },
    { field: 'azure_content_safety_key', label: 'API Key', type: 'password', required: true },
  ],
  palo_alto_airs: [
    { field: 'palo_alto_api_key', label: 'Prisma AIRS API Key', type: 'password', required: true },
    { field: 'palo_alto_profile_name', label: 'Profile Name', type: 'text', required: true, placeholder: 'test-profile' },
    { field: 'palo_alto_host', label: 'Host URL', type: 'text', placeholder: 'https://service.api.aisecurity.paloaltonetworks.com', help: 'Optional — defaults to global endpoint' },
  ],
  cloudflare_firewall_ai: [
    { field: 'cloudflare_account_id', label: 'Cloudflare Account ID', type: 'text', required: true },
    { field: 'cloudflare_api_token', label: 'API Token', type: 'password', required: true },
    { field: 'cloudflare_gateway_id', label: 'AI Gateway ID', type: 'text', placeholder: 'my-ai-gateway' },
  ],
};

interface EditProviderModalProps {
  provider: { id: string; display_name: string };
  config: AppConfig;
  locked: boolean;
  onSave: (updates: Partial<AppConfigUpdate>) => Promise<void>;
  onClose: () => void;
}

const EditProviderModal: React.FC<EditProviderModalProps> = ({ provider, config, locked, onSave, onClose }) => {
  const schema = PROVIDER_FIELD_SCHEMAS[provider.id] || [];
  // Snapshot of the current values so unsaved edits don't immediately mutate.
  const initial: Record<string, string> = {};
  for (const f of schema) initial[f.field] = ((config as any)[f.field] ?? '') as string;
  const [values, setValues] = React.useState<Record<string, string>>(initial);
  const [reveal, setReveal] = React.useState<Record<string, boolean>>({});
  const [saving, setSaving] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const dirty = schema.some(f => values[f.field] !== initial[f.field]);

  const save = async () => {
    // Required-field guard
    const missing = schema.filter(f => f.required && !(values[f.field] || '').trim()).map(f => f.label);
    if (missing.length) {
      setErr(`Required: ${missing.join(', ')}`);
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      // Only send fields that actually changed — keeps PUT /api/config diff
      // small + plays well with the demo-safe lock's value-comparison logic.
      const updates: any = {};
      for (const f of schema) {
        if (values[f.field] !== initial[f.field]) updates[f.field] = values[f.field];
      }
      await onSave(updates);
      onClose();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-3 border-b border-gray-200 dark:border-slate-700 flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-slate-100">Edit {provider.display_name}</h3>
            <div className="text-xs text-gray-500 dark:text-slate-400 font-mono mt-0.5">{provider.id}</div>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 dark:hover:text-slate-200 text-xl leading-none">×</button>
        </div>
        <div className="p-4 overflow-auto flex-1 space-y-3">
          {locked && (
            <div className="p-2 rounded bg-amber-50 border border-amber-200 text-xs text-amber-800">
              🔒 Provider config is locked. Unlock from the LLM or Security tab to save changes here.
            </div>
          )}
          {schema.length === 0 && (
            <div className="text-sm text-gray-500 italic">
              No editable fields registered for this provider. Add a schema in PROVIDER_FIELD_SCHEMAS.
            </div>
          )}
          {schema.map(f => {
            const isSecret = f.type === 'password';
            const showVal = !isSecret || reveal[f.field];
            return (
              <div key={f.field}>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">
                  {f.label}{f.required && <span className="text-red-600 ml-0.5">*</span>}
                </label>
                <div className="relative">
                  <input
                    type={showVal ? 'text' : 'password'}
                    value={values[f.field] || ''}
                    placeholder={f.placeholder}
                    disabled={locked || saving}
                    onChange={e => setValues({ ...values, [f.field]: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800 dark:text-slate-100 font-mono text-sm pr-9 disabled:opacity-60"
                  />
                  {isSecret && (
                    <button
                      type="button"
                      onClick={() => setReveal({ ...reveal, [f.field]: !reveal[f.field] })}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                      title={reveal[f.field] ? 'Hide' : 'Reveal'}
                    >
                      {reveal[f.field] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  )}
                </div>
                {f.help && <div className="text-xs text-gray-500 dark:text-slate-400 mt-1">{f.help}</div>}
              </div>
            );
          })}
          {err && <div className="text-sm text-red-600 dark:text-red-400">⚠ {err}</div>}
        </div>
        <div className="px-4 py-3 border-t border-gray-200 dark:border-slate-700 flex justify-end gap-2">
          <button onClick={onClose} disabled={saving}
            className="px-3 py-1.5 rounded text-sm bg-gray-100 dark:bg-slate-700 dark:text-slate-100 disabled:opacity-50">
            Cancel
          </button>
          <button onClick={save} disabled={locked || saving || !dirty}
            className="px-3 py-1.5 rounded text-sm bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50">
            {saving ? 'Saving…' : (dirty ? 'Save changes' : 'No changes')}
          </button>
        </div>
      </div>
    </div>
  );
};

const ProvidersTab: React.FC<ProvidersTabProps> = ({
  providers, guardrailProviders, config, onConfigUpdate, onActivate,
}) => {
  const locked = !!config.provider_config_locked;
  const disabledList: string[] = (config as any).disabled_providers || [];
  const [editing, setEditing] = React.useState<{ id: string; display_name: string } | null>(null);

  const toggleEnabled = async (id: string, currentEnabled: boolean) => {
    const next = currentEnabled
      ? [...disabledList, id]
      : disabledList.filter(x => x !== id);
    await onConfigUpdate({ disabled_providers: next } as any);
  };

  const isConfiguredLLM = (p: ProviderInfo): boolean => {
    if (p.needs_key === false) return true;
    if (!p.key_field) return true;
    return Boolean((config as any)[p.key_field]);
  };
  const isConfiguredGuard = (p: GuardrailProviderInfo): boolean => {
    // All listed guardrail providers need at least one key field set
    const cfg = config as any;
    switch (p.id) {
      case 'lakera': return Boolean(cfg.lakera_api_key);
      case 'openai_moderation': return Boolean(cfg.openai_api_key);
      case 'bedrock': return Boolean(cfg.bedrock_access_key_id && cfg.bedrock_secret_access_key);
      case 'azure_content_safety': return Boolean(cfg.azure_content_safety_endpoint && cfg.azure_content_safety_key);
      case 'palo_alto_airs': return Boolean(cfg.palo_alto_api_key);
      case 'cloudflare_firewall_ai': return Boolean(cfg.cloudflare_account_id && cfg.cloudflare_api_token);
      default: return false;
    }
  };

  const renderRow = (
    p: { id: string; display_name: string; enabled?: boolean; is_active?: boolean },
    kind: 'llm' | 'guardrail',
    configured: boolean,
  ) => {
    const enabled = p.enabled !== false;
    const isActive = !!p.is_active;
    const statusBadge = !configured
      ? <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-slate-300">no key</span>
      : !enabled
      ? <span className="px-2 py-0.5 text-xs rounded bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">disabled</span>
      : <span className="px-2 py-0.5 text-xs rounded bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200">configured</span>;
    const hasSchema = PROVIDER_FIELD_SCHEMAS[p.id]?.length > 0;
    return (
      <tr key={p.id} className="border-b border-gray-100 dark:border-slate-800">
        <td className="py-2 px-3">
          <div className="font-medium text-gray-900 dark:text-slate-100">{p.display_name}</div>
          <div className="text-xs text-gray-500 dark:text-slate-400 font-mono">{p.id}</div>
        </td>
        <td className="py-2 px-3">{statusBadge}</td>
        <td className="py-2 px-3 text-center">
          <input
            type="radio"
            name={`active-${kind}`}
            checked={isActive}
            disabled={locked || !configured || !enabled}
            onChange={() => onActivate(kind, p.id)}
            title={!configured ? 'Configure key first' : !enabled ? 'Enable first' : isActive ? 'Currently active' : 'Make active'}
          />
        </td>
        <td className="py-2 px-3 text-center">
          <button
            type="button"
            disabled={locked}
            onClick={() => toggleEnabled(p.id, enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              enabled ? 'bg-green-600' : 'bg-gray-300 dark:bg-slate-600'
            } ${locked ? 'opacity-50 cursor-not-allowed' : ''}`}
            title={enabled ? 'Click to disable' : 'Click to enable'}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </button>
        </td>
        <td className="py-2 px-3 text-center">
          <button
            type="button"
            disabled={!hasSchema}
            onClick={() => setEditing({ id: p.id, display_name: p.display_name })}
            className="px-2 py-1 text-xs rounded bg-gray-100 dark:bg-slate-700 dark:text-slate-100 hover:bg-gray-200 dark:hover:bg-slate-600 disabled:opacity-40"
            title={hasSchema ? 'Edit provider keys' : 'No schema registered for this provider yet'}
          >
            {configured ? 'Edit' : 'Configure'}
          </button>
        </td>
      </tr>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-slate-100">Provider Management</h2>
        <p className="text-sm text-gray-600 dark:text-slate-400 mt-1">
          One place to manage LLM and Guardrail providers. Toggle <strong>Enabled</strong> to include/exclude
          from runtime fan-out (compare, matrix, health). Use the <strong>Active</strong> radio to pick which
          one handles the live chat flow. Click <strong>Edit</strong> to update API keys for each provider.
        </p>
        {locked && (
          <div className="mt-2 p-2 rounded bg-amber-50 border border-amber-200 text-xs text-amber-800">
            🔒 Provider config is locked — Enable/Disable + Active changes blocked. Unlock from LLM/Security tab.
          </div>
        )}
      </div>

      <div>
        <h3 className="font-semibold text-gray-900 dark:text-slate-200 mb-2">LLM Providers ({providers.length})</h3>
        <table className="w-full text-sm border border-gray-200 dark:border-slate-700 rounded">
          <thead className="bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300">
            <tr>
              <th className="py-2 px-3 text-left">Provider</th>
              <th className="py-2 px-3 text-left w-32">Status</th>
              <th className="py-2 px-3 text-center w-24">Active</th>
              <th className="py-2 px-3 text-center w-24">Enabled</th>
              <th className="py-2 px-3 text-center w-24">Actions</th>
            </tr>
          </thead>
          <tbody>{providers.map(p => renderRow(p, 'llm', isConfiguredLLM(p)))}</tbody>
        </table>
      </div>

      <div>
        <h3 className="font-semibold text-gray-900 dark:text-slate-200 mb-2">Guardrail Providers ({guardrailProviders.length})</h3>
        <table className="w-full text-sm border border-gray-200 dark:border-slate-700 rounded">
          <thead className="bg-gray-50 dark:bg-slate-800 text-gray-700 dark:text-slate-300">
            <tr>
              <th className="py-2 px-3 text-left">Provider</th>
              <th className="py-2 px-3 text-left w-32">Status</th>
              <th className="py-2 px-3 text-center w-24">Active</th>
              <th className="py-2 px-3 text-center w-24">Enabled</th>
              <th className="py-2 px-3 text-center w-24">Actions</th>
            </tr>
          </thead>
          <tbody>{guardrailProviders.map(p => renderRow(p, 'guardrail', isConfiguredGuard(p)))}</tbody>
        </table>
      </div>

      {editing && (
        <EditProviderModal
          provider={editing}
          config={config}
          locked={locked}
          onSave={onConfigUpdate}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
};

export default AdminConsole;


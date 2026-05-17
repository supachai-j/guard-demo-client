import {
  AppConfig,
  AppConfigUpdate,
  ChatRequest,
  ChatResponse,
  RagGenerateRequest,
  RagGenerateResponse,
  Tool,
  ToolCreate,
  ToolUpdate,
  LakeraResult,
  DemoPrompt,
  DemoPromptCreate,
  DemoPromptUpdate,
  DemoPromptSearchResponse,
  ScenarioPreview,
  ApplyScenarioResponse
} from '../types';

const API_BASE = '/api';

const TOKEN_STORAGE_KEY = 'admin_token';

/** Auth token getter — kept here so non-React modules (services, lifecycle
 * hooks) can read the same source as the AuthContext writes to. */
const getToken = (): string | null => {
  try { return localStorage.getItem(TOKEN_STORAGE_KEY); } catch { return null; }
};

const clearTokenAndRedirect = () => {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem('admin_user');
    localStorage.removeItem('admin_token_exp');
  } catch { /* ignore */ }
  // Avoid bouncing the login page on itself.
  if (typeof window !== 'undefined' && !window.location.pathname.endsWith('/login')) {
    const dest = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.replace(`/login?next=${dest}`);
  }
};

class ApiService {
  private async parseError(response: Response, fallback: string): Promise<never> {
    let detail = fallback;
    try {
      const raw = await response.text();
      const payload = raw ? JSON.parse(raw) : {};
      detail = payload?.detail || payload?.message || fallback;
    } catch {
      // keep fallback
    }
    throw new Error(String(detail));
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    // Auto-attach the Bearer token if one is stored. Skip for the login + auth
    // status endpoints so a stale token can't fail a fresh login attempt.
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string> | undefined),
    };
    const token = getToken();
    const skipAuth = endpoint.startsWith('/auth/login') || endpoint.startsWith('/auth/status');
    if (token && !skipAuth && !headers.Authorization) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 401 && !skipAuth) {
      clearTokenAndRedirect();
      throw new Error('Session expired. Please log in again.');
    }

    if (!response.ok) return this.parseError(response, `API request failed: ${response.statusText}`);

    return response.json();
  }

  // Config endpoints
  async getConfig(): Promise<AppConfig> {
    return this.request<AppConfig>('/config');
  }

  async updateConfig(config: Partial<AppConfigUpdate>): Promise<{ message: string }> {
    // Backend uses Pydantic's exclude_unset=True — sending only the fields
    // that actually need to change is correct and required for the demo-safe
    // lock's value-comparison check (commit e16e61c).
    return this.request<{ message: string }>('/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    });
  }

  async exportConfig(include?: string[]): Promise<Blob> {
    const params = new URLSearchParams();
    params.set('version', '2'); // always request v2 export (metadata.version 2.0, includes demo_prompts.json)
    if (include && include.length > 0) {
      params.set('include', include.join(','));
    }
    const url = `${API_BASE}/config/export?${params.toString()}`;
    const token = getToken();
    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (response.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!response.ok) {
      throw new Error('Export failed');
    }
    return response.blob();
  }

  async importConfig(file: File): Promise<{ message: string; imported_at?: string; metadata?: { includes?: string[]; version?: string } }> {
    const formData = new FormData();
    formData.append('file', file);

    const token = getToken();
    const response = await fetch(`${API_BASE}/config/import`, {
      method: 'POST',
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });

    if (response.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!response.ok) {
      return this.parseError(response, 'Import failed');
    }

    return response.json();
  }

  // Chat endpoints
  async sendMessage(request: ChatRequest): Promise<ChatResponse> {
    return this.request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // RAG endpoints
  async uploadFile(file: File): Promise<{ message: string; filename?: string; result?: { chunks?: number; blocked_chunks?: number } }> {
    const formData = new FormData();
    formData.append('file', file);

    const token = getToken();
    const response = await fetch(`${API_BASE}/rag/upload`, {
      method: 'POST',
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });

    if (response.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!response.ok) {
      return this.parseError(response, 'File upload failed');
    }

    return response.json();
  }

  async generateRagContent(request: RagGenerateRequest): Promise<RagGenerateResponse> {
    return this.request<RagGenerateResponse>('/rag/generate', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async searchRag(query: string): Promise<any> {
    return this.request(`/rag/search?q=${encodeURIComponent(query)}`);
  }

  async getRagSources(): Promise<{ sources: any[] }> {
    return this.request<{ sources: any[] }>('/rag/sources');
  }

  async clearRagContent(): Promise<{ message: string }> {
    return this.request<{ message: string }>('/rag/clear', {
      method: 'DELETE',
    });
  }

  // Tools endpoints
  async getTools(): Promise<Tool[]> {
    return this.request<Tool[]>('/tools');
  }

  async createTool(tool: ToolCreate): Promise<Tool> {
    return this.request<Tool>('/tools', {
      method: 'POST',
      body: JSON.stringify(tool),
    });
  }

  async updateTool(id: number, tool: ToolUpdate): Promise<Tool> {
    return this.request<Tool>(`/tools/${id}`, {
      method: 'PUT',
      body: JSON.stringify(tool),
    });
  }

  async deleteTool(id: number): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/tools/${id}`, {
      method: 'DELETE',
    });
  }

  async testTool(id: number, parameters: any): Promise<any> {
    return this.request(`/tools/test/${id}`, {
      method: 'POST',
      body: JSON.stringify(parameters),
    });
  }

  // Lakera endpoints
  async getLastLakeraResult(): Promise<LakeraResult> {
    return this.request<LakeraResult>('/lakera/last');
  }

  async getLastRagScanningResult(): Promise<any> {
    return this.request<any>('/rag/scanning/last');
  }

  async getRagScanningProgress(): Promise<any> {
    return this.request<any>('/rag/scanning/progress');
  }

  // Demo Prompt endpoints
  async getDemoPrompts(category?: string, limit: number = 50): Promise<DemoPrompt[]> {
    const params = new URLSearchParams();
    if (category) params.append('category', category);
    params.append('limit', limit.toString());
    return this.request<DemoPrompt[]>(`/demo-prompts?${params.toString()}`);
  }

  async searchDemoPrompts(query: string, category?: string, limit: number = 10): Promise<DemoPromptSearchResponse> {
    const params = new URLSearchParams();
    params.append('q', query);
    if (category) params.append('category', category);
    params.append('limit', limit.toString());
    return this.request<DemoPromptSearchResponse>(`/demo-prompts/search?${params.toString()}`);
  }

  async createDemoPrompt(prompt: DemoPromptCreate): Promise<DemoPrompt> {
    return this.request<DemoPrompt>('/demo-prompts', {
      method: 'POST',
      body: JSON.stringify(prompt),
    });
  }

  async updateDemoPrompt(id: number, prompt: DemoPromptUpdate): Promise<DemoPrompt> {
    return this.request<DemoPrompt>(`/demo-prompts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(prompt),
    });
  }

  async deleteDemoPrompt(id: number): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/demo-prompts/${id}`, {
      method: 'DELETE',
    });
  }

  async useDemoPrompt(id: number): Promise<{ message: string; usage_count: number }> {
    return this.request<{ message: string; usage_count: number }>(`/demo-prompts/${id}/use`, {
      method: 'POST',
    });
  }

  // Models endpoint
  async getModels(): Promise<{ models: string[] }> {
    return this.request<{ models: string[] }>('/models');
  }

  // Provider catalog (multi-provider Security tab)
  async getProviders(): Promise<{ providers: import('../types').ProviderInfo[] }> {
    return this.request<{ providers: import('../types').ProviderInfo[] }>('/providers');
  }

  async getGuardrailProviders(): Promise<{ providers: import('../types').GuardrailProviderInfo[] }> {
    return this.request<{ providers: import('../types').GuardrailProviderInfo[] }>('/guardrail-providers');
  }

  // Scenario (one-click company switcher) endpoints
  async listScenarios(): Promise<{ scenarios: ScenarioPreview[] }> {
    return this.request<{ scenarios: ScenarioPreview[] }>('/scenarios');
  }

  async applyScenario(scenarioId: string): Promise<ApplyScenarioResponse> {
    return this.request<ApplyScenarioResponse>(`/scenarios/${scenarioId}/apply`, {
      method: 'POST',
    });
  }

  // Audit log
  async getAuditLog(opts?: { limit?: number; flagged_only?: boolean }): Promise<{ entries: any[]; count: number }> {
    const params = new URLSearchParams();
    if (opts?.limit) params.set('limit', String(opts.limit));
    if (opts?.flagged_only) params.set('flagged_only', 'true');
    return this.request(`/audit?${params.toString()}`);
  }

  exportAuditCsvUrl(): string {
    // CSV/PDF downloads are triggered via <a href>, so we can't attach an
    // Authorization header — fetch the file via blob with token instead.
    return `${API_BASE}/audit?format=csv&limit=1000`;
  }

  async downloadAuditCsv(): Promise<Blob> {
    const token = getToken();
    const resp = await fetch(`${API_BASE}/audit?format=csv&limit=1000`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (resp.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!resp.ok) throw new Error('Audit CSV download failed');
    return resp.blob();
  }

  async downloadAuditPdf(): Promise<Blob> {
    const token = getToken();
    const resp = await fetch(`${API_BASE}/audit/report.pdf?limit=500`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (resp.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!resp.ok) throw new Error('Audit PDF download failed');
    return resp.blob();
  }

  async clearAuditLog(): Promise<{ deleted: number }> {
    return this.request('/audit', { method: 'DELETE' });
  }

  // Conversation history (multi-turn memory)
  async listConversations(): Promise<{ conversations: any[] }> {
    return this.request('/conversations');
  }

  async getConversation(id: number): Promise<{ id: number; title: string; messages: any[] }> {
    return this.request(`/conversations/${id}`);
  }

  async deleteConversation(id: number): Promise<{ deleted: number }> {
    return this.request(`/conversations/${id}`, { method: 'DELETE' });
  }

  // Guardrail compare
  async compareGuardrails(message: string): Promise<{ message: string; results: any[] }> {
    return this.request('/chat/compare-guardrails', {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  }

  // Image moderation
  async moderateImage(imageDataUrl: string): Promise<{ supported: boolean; provider: string; status: any }> {
    return this.request('/moderation/image', {
      method: 'POST',
      body: JSON.stringify({ image_data_url: imageDataUrl }),
    });
  }

  // OWASP / playbooks
  async listPlaybooks(): Promise<{ playbooks: { id: string; name: string; docs_url?: string; count: number; is_builtin?: boolean }[] }> {
    return this.request('/playbooks');
  }

  async getPlaybook(id: string): Promise<any> {
    return this.request(`/playbooks/${encodeURIComponent(id)}`);
  }

  async runPlaybook(id: string): Promise<any> {
    return this.request(`/playbooks/${encodeURIComponent(id)}/run`, { method: 'POST' });
  }

  async createPlaybook(payload: { name: string; description?: string; prompts: any[] }): Promise<any> {
    return this.request('/playbooks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updatePlaybook(id: string, payload: { name?: string; description?: string; prompts?: any[] }): Promise<any> {
    return this.request(`/playbooks/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deletePlaybook(id: string): Promise<{ deleted: number }> {
    return this.request(`/playbooks/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  // Playbook run history
  async listPlaybookRuns(filters?: { playbook_slug?: string; guardrail_provider?: string; limit?: number }): Promise<{ runs: any[]; count: number }> {
    const q = new URLSearchParams();
    if (filters?.playbook_slug) q.set('playbook_slug', filters.playbook_slug);
    if (filters?.guardrail_provider) q.set('guardrail_provider', filters.guardrail_provider);
    if (filters?.limit) q.set('limit', String(filters.limit));
    const qs = q.toString();
    return this.request(`/playbook-runs${qs ? '?' + qs : ''}`);
  }

  async getPlaybookRun(id: number): Promise<any> {
    return this.request(`/playbook-runs/${id}`);
  }

  async comparePlaybookRuns(ids: number[]): Promise<any> {
    return this.request(`/playbook-runs/compare?ids=${ids.join(',')}`);
  }

  async runPlaybookMultiProvider(playbook_id: string, provider_ids: string[]): Promise<any> {
    return this.request('/playbook-runs/multi-provider', {
      method: 'POST',
      body: JSON.stringify({ playbook_id, provider_ids }),
    });
  }

  async runPlaybookMatrix(playbook_ids: string[], provider_ids: string[]): Promise<any> {
    return this.request('/playbook-runs/matrix', {
      method: 'POST',
      body: JSON.stringify({ playbook_ids, provider_ids }),
    });
  }

  async deletePlaybookRun(id: number): Promise<{ deleted: number; id: number }> {
    return this.request(`/playbook-runs/${id}`, { method: 'DELETE' });
  }

  async updatePlaybookRunNotes(id: number, notes: string): Promise<any> {
    return this.request(`/playbook-runs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ notes }),
    });
  }

  // Recordings
  async listRecordings(): Promise<{ recordings: any[] }> {
    return this.request('/recordings');
  }

  async createRecording(name: string, events: any[], notes?: string): Promise<{ id: number }> {
    return this.request('/recordings', {
      method: 'POST',
      body: JSON.stringify({ name, events, notes }),
    });
  }

  async replayRecording(id: number): Promise<{ results: any[] }> {
    return this.request(`/recordings/${id}/replay`, { method: 'POST' });
  }

  async deleteRecording(id: number): Promise<{ deleted: number }> {
    return this.request(`/recordings/${id}`, { method: 'DELETE' });
  }

  // Cost summary
  async getCostSummary(): Promise<{ total_cost_usd: number; total_input_tokens: number; total_output_tokens: number; by_provider: any[] }> {
    return this.request('/audit/cost-summary');
  }

  exportAuditPdfUrl(): string {
    return `${API_BASE}/audit/report.pdf?limit=500`;
  }

  // Compare LLMs (fan to multiple LLM providers)
  async compareLlms(message: string, providers: { provider: string; model: string }[]): Promise<{ message: string; results: any[] }> {
    return this.request('/chat/compare-llms', {
      method: 'POST',
      body: JSON.stringify({ message, providers }),
    });
  }

  // Health checks
  async healthProviders(): Promise<{ providers: any[] }> {
    return this.request('/health/providers');
  }

  // Batch eval — CSV upload
  async batchRun(file: File): Promise<any> {
    const fd = new FormData();
    fd.append('file', file);
    const token = getToken();
    const resp = await fetch(`${API_BASE}/batch/run`, {
      method: 'POST',
      body: fd,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (resp.status === 401) { clearTokenAndRedirect(); throw new Error('Session expired'); }
    if (!resp.ok) return this.parseError(resp, 'batch run failed');
    return resp.json();
  }

  // Webhook test
  async testWebhook(url: string): Promise<{ ok: boolean; status: number; body?: string; error?: string }> {
    return this.request('/webhook/test', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  }

  // Auth status (does admin auth env-gate require basic auth?)
  async authStatus(): Promise<{ enabled: boolean }> {
    return this.request('/auth/status');
  }

  /** URL for the live audit stream (consumed via EventSource).
   *  EventSource can't set Authorization headers, so we pass the JWT as a
   *  query param — the backend validates it the same way require_admin does. */
  auditStreamUrl(opts?: { flaggedOnly?: boolean }): string | null {
    const token = getToken();
    if (!token) return null;
    const params = new URLSearchParams();
    params.set('token', token);
    params.set('flagged_only', opts?.flaggedOnly === false ? 'false' : 'true');
    return `${API_BASE}/audit/stream?${params.toString()}`;
  }

  // Streaming chat — returns an async iterator of token strings.
  async *streamChat(message: string, conversationId?: number, sessionId?: string): AsyncGenerator<{ kind: 'chunk' | 'done' | 'blocked' | 'error'; data: any }> {
    const token = getToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    const resp = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message, conversation_id: conversationId, session_id: sessionId }),
    });
    if (!resp.body) throw new Error('No streaming response body');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const lines = raw.split('\n');
        let event = 'message';
        let data = '';
        for (const line of lines) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        }
        let parsed: any = null;
        try { parsed = data ? JSON.parse(data) : null; } catch { /* ignore */ }
        yield { kind: event as any, data: parsed };
      }
    }
  }
}

export const apiService = new ApiService();


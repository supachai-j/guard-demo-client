import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Edit3, X, Save, Lock, Copy, ImagePlus, Download } from 'lucide-react';
import { apiService } from '../services/api';

type CatalogEntry = {
  id: string;
  name: string;
  count: number;
  is_builtin?: boolean;
};

type PromptRow = {
  id: string;
  category: string;
  prompt: string;
  expected: 'blocked' | 'allowed';
  description?: string;
  // Optional base64 data URL for image-injection / multimodal scenarios (4.3.14, 4.3.19).
  image_b64?: string;
};

type PlaybookDetail = {
  id: string;
  name: string;
  description?: string;
  prompts: PromptRow[];
  is_builtin?: boolean;
};

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged: () => void; // notify parent to refresh catalog
}

const emptyRow = (idx: number): PromptRow => ({
  id: `P${idx}`,
  category: 'Custom',
  prompt: '',
  expected: 'blocked',
});

const PlaybookManager: React.FC<Props> = ({ open, onClose, onChanged }) => {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<PlaybookDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCatalog = async () => {
    setLoading(true);
    try {
      const data = await apiService.listPlaybooks();
      setCatalog(data.playbooks as CatalogEntry[]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setEditing(null);
      setError(null);
      loadCatalog();
    }
  }, [open]);

  if (!open) return null;

  const startNew = () => {
    setError(null);
    setEditing({
      id: '',
      name: '',
      description: '',
      prompts: [emptyRow(1)],
      is_builtin: false,
    });
  };

  const startEdit = async (id: string) => {
    setError(null);
    try {
      const data = await apiService.getPlaybook(id);
      setEditing({
        id: data.id,
        name: data.name,
        description: data.description || '',
        prompts: (data.prompts || []).map((p: any) => ({
          id: p.id,
          category: p.category || 'Custom',
          prompt: p.prompt || '',
          expected: p.expected === 'allowed' ? 'allowed' : 'blocked',
          description: p.description,
          image_b64: p.image_b64,
        })),
        is_builtin: !!data.is_builtin,
      });
    } catch (e: any) {
      setError(e?.message || 'Failed to load playbook');
    }
  };

  const duplicate = async (id: string) => {
    setError(null);
    try {
      const data = await apiService.getPlaybook(id);
      setEditing({
        id: '', // empty = create new
        name: `${data.name} (copy)`,
        description: data.description || '',
        prompts: (data.prompts || []).map((p: any) => ({
          id: p.id,
          category: p.category || 'Custom',
          prompt: p.prompt || '',
          expected: p.expected === 'allowed' ? 'allowed' : 'blocked',
          description: p.description,
          image_b64: p.image_b64,
        })),
        is_builtin: false,
      });
    } catch (e: any) {
      setError(e?.message || 'Failed to duplicate playbook');
    }
  };

  const remove = async (entry: CatalogEntry) => {
    if (!window.confirm(`Delete playbook "${entry.name}"? This cannot be undone.`)) return;
    try {
      await apiService.deletePlaybook(entry.id);
      onChanged();
      await loadCatalog();
    } catch (e: any) {
      setError(e?.message || 'Delete failed');
    }
  };

  const save = async () => {
    if (!editing) return;
    if (!editing.name.trim()) {
      setError('Name is required');
      return;
    }
    if (editing.prompts.length === 0) {
      setError('Add at least one prompt');
      return;
    }
    for (const p of editing.prompts) {
      if (!p.id.trim() || !p.prompt.trim()) {
        setError('Every row needs both an ID and a prompt');
        return;
      }
    }
    const ids = editing.prompts.map(p => p.id.trim());
    if (new Set(ids).size !== ids.length) {
      setError('Prompt IDs must be unique within a playbook');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: editing.name.trim(),
        description: editing.description || undefined,
        prompts: editing.prompts.map(p => ({
          id: p.id.trim(),
          category: p.category.trim() || 'Custom',
          prompt: p.prompt,
          expected: p.expected,
          ...(p.image_b64 ? { image_b64: p.image_b64 } : {}),
        })),
      };
      if (editing.id) {
        await apiService.updatePlaybook(editing.id, payload);
      } else {
        await apiService.createPlaybook(payload);
      }
      onChanged();
      setEditing(null);
      await loadCatalog();
    } catch (e: any) {
      setError(e?.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const updateRow = (i: number, patch: Partial<PromptRow>) => {
    if (!editing) return;
    setEditing({
      ...editing,
      prompts: editing.prompts.map((p, idx) => (idx === i ? { ...p, ...patch } : p)),
    });
  };

  // Attach an image (base64 data URL) to a prompt row for multimodal scenarios.
  const attachImageToRow = (i: number, file: File | undefined) => {
    if (!file || !file.type.startsWith('image/')) return;
    if (file.size > 4 * 1024 * 1024) {
      setError('Image exceeds 4MB');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => updateRow(i, { image_b64: reader.result as string });
    reader.readAsDataURL(file);
  };

  const addRow = () => {
    if (!editing) return;
    setEditing({
      ...editing,
      prompts: [...editing.prompts, emptyRow(editing.prompts.length + 1)],
    });
  };

  const removeRow = (i: number) => {
    if (!editing) return;
    setEditing({
      ...editing,
      prompts: editing.prompts.filter((_, idx) => idx !== i),
    });
  };

  return (
    <div className="fixed inset-0 z-40 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-slate-800 rounded-lg shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-slate-700">
          <h3 className="font-semibold text-gray-900 dark:text-slate-100">
            {editing
              ? editing.id
                ? `Edit playbook: ${editing.name}`
                : 'New playbook'
              : 'Manage playbooks'}
          </h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="m-3 p-2 rounded bg-red-50 text-red-700 border border-red-200 text-sm">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4">
          {!editing && (
            <>
              <div className="mb-3 flex justify-between items-center">
                <span className="text-sm text-gray-600 dark:text-slate-400">
                  Built-in playbooks are read-only — duplicate one to start a customer-specific checklist.
                </span>
                <button
                  onClick={startNew}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm bg-primary-600 text-white hover:bg-primary-700"
                >
                  <Plus className="w-4 h-4" /> New playbook
                </button>
              </div>
              {loading ? (
                <div className="text-center text-gray-500 p-4">Loading…</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-gray-600 dark:text-slate-400 border-b border-gray-200 dark:border-slate-700">
                    <tr>
                      <th className="text-left p-2">Name</th>
                      <th className="text-left p-2 w-24">Prompts</th>
                      <th className="text-left p-2 w-24">Kind</th>
                      <th className="text-right p-2 w-44">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.map(p => (
                      <tr key={p.id} className="border-b border-gray-100 dark:border-slate-700">
                        <td className="p-2 dark:text-slate-200">
                          <div className="font-medium">{p.name}</div>
                          <div className="text-xs text-gray-500 dark:text-slate-500 font-mono">{p.id}</div>
                        </td>
                        <td className="p-2 dark:text-slate-300">{p.count}</td>
                        <td className="p-2">
                          {p.is_builtin ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300">
                              <Lock className="w-3 h-3" /> built-in
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-emerald-50 text-emerald-700 border border-emerald-200">
                              custom
                            </span>
                          )}
                        </td>
                        <td className="p-2 text-right">
                          <a
                            href={apiService.exportPlaybookCsvUrl(p.id)}
                            title="Export prompts as CSV"
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-600 mr-1"
                          >
                            <Download className="w-3 h-3" /> CSV
                          </a>
                          <button
                            onClick={() => duplicate(p.id)}
                            title="Duplicate"
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-600 mr-1"
                          >
                            <Copy className="w-3 h-3" /> Duplicate
                          </button>
                          {!p.is_builtin && (
                            <>
                              <button
                                onClick={() => startEdit(p.id)}
                                title="Edit"
                                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-primary-50 text-primary-700 hover:bg-primary-100 mr-1"
                              >
                                <Edit3 className="w-3 h-3" /> Edit
                              </button>
                              <button
                                onClick={() => remove(p)}
                                title="Delete"
                                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-50 text-red-700 hover:bg-red-100"
                              >
                                <Trash2 className="w-3 h-3" /> Delete
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {editing && (
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={editing.name}
                  onChange={e => setEditing({ ...editing, name: e.target.value })}
                  placeholder="Acme Inc — POC verification"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-900 dark:text-slate-100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-200 mb-1">
                  Description <span className="text-xs text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={editing.description || ''}
                  onChange={e => setEditing({ ...editing, description: e.target.value })}
                  placeholder="Per-customer notes about scope"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-900 dark:text-slate-100"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700 dark:text-slate-200">
                    Prompts ({editing.prompts.length})
                  </label>
                  <button
                    onClick={addRow}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-600"
                  >
                    <Plus className="w-3 h-3" /> Add row
                  </button>
                </div>
                <div className="border border-gray-200 dark:border-slate-700 rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 dark:bg-slate-900/50 text-gray-600 dark:text-slate-300">
                      <tr>
                        <th className="text-left p-2 w-20">ID</th>
                        <th className="text-left p-2 w-32">Category</th>
                        <th className="text-left p-2 w-28">Expected</th>
                        <th className="text-left p-2">Prompt</th>
                        <th className="text-right p-2 w-10"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {editing.prompts.map((p, i) => (
                        <tr key={i} className="border-t border-gray-100 dark:border-slate-700">
                          <td className="p-1">
                            <input
                              type="text"
                              value={p.id}
                              onChange={e => updateRow(i, { id: e.target.value })}
                              className="w-full px-1.5 py-1 border border-transparent hover:border-gray-300 dark:hover:border-slate-600 rounded bg-transparent dark:text-slate-100 font-mono text-[11px]"
                            />
                          </td>
                          <td className="p-1">
                            <input
                              type="text"
                              value={p.category}
                              onChange={e => updateRow(i, { category: e.target.value })}
                              className="w-full px-1.5 py-1 border border-transparent hover:border-gray-300 dark:hover:border-slate-600 rounded bg-transparent dark:text-slate-100"
                            />
                          </td>
                          <td className="p-1">
                            <select
                              value={p.expected}
                              onChange={e => updateRow(i, { expected: e.target.value as 'blocked' | 'allowed' })}
                              className="w-full px-1.5 py-1 border border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-900 dark:text-slate-100"
                            >
                              <option value="blocked">blocked</option>
                              <option value="allowed">allowed</option>
                            </select>
                          </td>
                          <td className="p-1">
                            <textarea
                              value={p.prompt}
                              onChange={e => updateRow(i, { prompt: e.target.value })}
                              rows={1}
                              className="w-full px-1.5 py-1 border border-transparent hover:border-gray-300 dark:hover:border-slate-600 rounded bg-transparent dark:text-slate-100 resize-y min-h-[28px]"
                            />
                            <div className="flex items-center gap-2 mt-1">
                              {p.image_b64 ? (
                                <div className="relative inline-block">
                                  <img src={p.image_b64} alt="prompt attachment" className="w-10 h-10 object-cover rounded border border-gray-300 dark:border-slate-600" />
                                  <button
                                    onClick={() => updateRow(i, { image_b64: undefined })}
                                    className="absolute -top-1.5 -right-1.5 bg-gray-700 text-white rounded-full p-0.5 hover:bg-gray-900"
                                    title="Remove image"
                                  >
                                    <X className="w-2.5 h-2.5" />
                                  </button>
                                </div>
                              ) : (
                                <label className="text-[10px] text-gray-400 hover:text-primary-600 cursor-pointer inline-flex items-center gap-1">
                                  <ImagePlus className="w-3 h-3" />
                                  <span>image</span>
                                  <input
                                    type="file"
                                    accept="image/*"
                                    className="hidden"
                                    onChange={e => { attachImageToRow(i, e.target.files?.[0]); e.target.value = ''; }}
                                  />
                                </label>
                              )}
                            </div>
                          </td>
                          <td className="p-1 text-right">
                            <button
                              onClick={() => removeRow(i)}
                              className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50"
                              title="Remove row"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-gray-200 dark:border-slate-700">
          {editing ? (
            <>
              <button
                onClick={() => setEditing(null)}
                className="px-3 py-1.5 rounded text-sm bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-600"
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
              >
                <Save className="w-4 h-4" /> {saving ? 'Saving…' : 'Save playbook'}
              </button>
            </>
          ) : (
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded text-sm bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-600"
            >
              Close
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default PlaybookManager;

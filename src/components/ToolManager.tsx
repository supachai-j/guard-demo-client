import React, { useState, useEffect } from 'react';
import { Plus, Settings, Play, Trash2, Search, Layers, Network } from 'lucide-react';
import { Tool, ToolCreate, ToolCapabilities, DiscoveredMcpTool } from '../types';
import { apiService } from '../services/api';

const ToolManager: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [testResults, setTestResults] = useState<Record<number, any>>({});
  // Write-only gateway key input — separate from editingTool because the
  // stored key is never returned (we only know whether one is set).
  const [gatewayKeyInput, setGatewayKeyInput] = useState('');
  // Per-tool capability browser state. Only one row's panel is open at a time
  // (toggling another row collapses the first) so the page stays scannable.
  const [expandedCaps, setExpandedCaps] = useState<number | null>(null);
  const [capsLoading, setCapsLoading] = useState<Record<number, boolean>>({});
  const [capsByTool, setCapsByTool] = useState<Record<number, ToolCapabilities | null>>({});
  const [capsError, setCapsError] = useState<Record<number, string>>({});

  const [newTool, setNewTool] = useState<ToolCreate>({
    name: '',
    description: '',
    endpoint: '',
    type: 'mcp',
    enabled: true,
    config_json: {},
  });

  useEffect(() => {
    loadTools();
  }, []);

  const loadTools = async () => {
    setIsLoading(true);
    try {
      const toolsData = await apiService.getTools();
      setTools(toolsData);
    } catch (error) {
      console.error('Failed to load tools:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddTool = async () => {
    try {
      await apiService.createTool(newTool);
      setNewTool({
        name: '',
        description: '',
        endpoint: '',
        type: 'mcp',
        enabled: true,
        config_json: {},
      });
      setShowAddForm(false);
      await loadTools();
    } catch (error) {
      console.error('Failed to add tool:', error);
    }
  };

  const handleUpdateTool = async (tool: Tool) => {
    try {
      await apiService.updateTool(tool.id, {
        name: tool.name,
        description: tool.description,
        endpoint: tool.endpoint,
        type: tool.type,
        enabled: tool.enabled,
        config_json: tool.config_json,
        gateway_enabled: tool.gateway_enabled,
        gateway_url: tool.gateway_url,
        // Only send the key when the operator typed a new one; blank preserves
        // the stored secret (write-only on the backend).
        ...(gatewayKeyInput.trim() ? { gateway_api_key: gatewayKeyInput } : {}),
      });
      setGatewayKeyInput('');
      setEditingTool(null);
      await loadTools();
    } catch (error) {
      console.error('Failed to update tool:', error);
    }
  };

  const handleDeleteTool = async (toolId: number) => {
    if (!confirm('Are you sure you want to delete this tool?')) return;
    
    try {
      await apiService.deleteTool(toolId);
      await loadTools();
    } catch (error) {
      console.error('Failed to delete tool:', error);
    }
  };

  const handleTestTool = async (toolId: number) => {
    try {
      const result = await apiService.testTool(toolId, { test: true });
      setTestResults(prev => ({ ...prev, [toolId]: result }));
      // A successful test rediscovers capabilities, so invalidate any cached
      // panel data — next open will refetch the new tools list.
      setCapsByTool(prev => ({ ...prev, [toolId]: null }));
    } catch (error) {
      console.error('Failed to test tool:', error);
      setTestResults(prev => ({ ...prev, [toolId]: { error: 'Test failed' } }));
    }
  };

  const loadCapabilities = async (toolId: number) => {
    setCapsLoading(prev => ({ ...prev, [toolId]: true }));
    setCapsError(prev => ({ ...prev, [toolId]: '' }));
    try {
      const caps = await apiService.getToolCapabilities(toolId);
      setCapsByTool(prev => ({ ...prev, [toolId]: caps }));
    } catch (e: any) {
      setCapsError(prev => ({ ...prev, [toolId]: String(e?.message || e) }));
    } finally {
      setCapsLoading(prev => ({ ...prev, [toolId]: false }));
    }
  };

  const toggleCapabilities = async (tool: Tool) => {
    if (expandedCaps === tool.id) {
      setExpandedCaps(null);
      return;
    }
    setExpandedCaps(tool.id);
    if (!capsByTool[tool.id]) {
      await loadCapabilities(tool.id);
    }
  };

  /** Flip one MCP tool's enabled/disabled state and PATCH the server. The
   * panel renders optimistically so the checkbox feels instant; on error
   * we reload the canonical state from the server. */
  const handleToggleDiscoveredTool = async (toolId: number, mcpName: string, nextDisabled: boolean) => {
    const caps = capsByTool[toolId];
    if (!caps) return;
    const current = new Set(caps.disabled_tools || []);
    if (nextDisabled) current.add(mcpName); else current.delete(mcpName);
    const nextList = Array.from(current);
    // Optimistic update.
    setCapsByTool(prev => ({
      ...prev,
      [toolId]: {
        ...caps,
        disabled_tools: nextList,
        tools: caps.tools.map(t => t.name === mcpName ? { ...t, disabled: nextDisabled } : t),
      },
    }));
    try {
      await apiService.updateDisabledTools(toolId, nextList);
    } catch (e: any) {
      setCapsError(prev => ({ ...prev, [toolId]: `Failed to save: ${String(e?.message || e)}` }));
      // Re-pull canonical state so the UI doesn't drift from the backend.
      await loadCapabilities(toolId);
    }
  };

  const filteredTools = tools.filter(tool =>
    tool.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    tool.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Search and Add */}
      <div className="flex justify-between items-center">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
          <input
            type="text"
            placeholder="Search tools..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="flex items-center space-x-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700"
        >
          <Plus className="w-4 h-4" />
          <span>Add Tool</span>
        </button>
      </div>

      {/* Add Tool Form */}
      {showAddForm && (
        <div className="bg-gray-50 p-6 rounded-lg border">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Add New Tool</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Name</label>
              <input
                type="text"
                value={newTool.name}
                onChange={(e) => setNewTool({ ...newTool, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Type</label>
              <select
                value={newTool.type}
                onChange={(e) => setNewTool({ ...newTool, type: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="mcp">MCP (SSE Endpoint)</option>
                <option value="http">HTTP (MCP Endpoint)</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
              <textarea
                value={newTool.description}
                onChange={(e) => setNewTool({ ...newTool, description: e.target.value })}
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">Endpoint</label>
              <input
                type="text"
                value={newTool.endpoint}
                onChange={(e) => setNewTool({ ...newTool, endpoint: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>
          <div className="flex justify-end space-x-2 mt-4">
            <button
              onClick={() => setShowAddForm(false)}
              className="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300"
            >
              Cancel
            </button>
            <button
              onClick={handleAddTool}
              disabled={!newTool.name}
              className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              Add Tool
            </button>
          </div>
        </div>
      )}

      {/* Tools List */}
      {isLoading ? (
        <div className="text-center py-8">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto"></div>
          <p className="mt-2 text-gray-600">Loading tools...</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredTools.map((tool) => (
            <div key={tool.id} className="bg-white border border-gray-200 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center space-x-3">
                    <h3 className="text-lg font-medium text-gray-900">{tool.name}</h3>
                    <span className={`px-2 py-1 text-xs rounded-full ${
                      tool.enabled 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      {tool.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded-full">
                      {tool.type.toUpperCase()}
                    </span>
                    {tool.type === 'mcp' && (
                      tool.gateway_enabled && tool.gateway_url ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-purple-100 text-purple-800 rounded-full" title={`Routed through AI Gateway: ${tool.gateway_url}`}>
                          <Network className="w-3 h-3" /> via AI Gateway
                        </span>
                      ) : (
                        <span className="px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded-full" title="Connects directly to the MCP endpoint">
                          direct
                        </span>
                      )
                    )}
                  </div>
                  {tool.description && (
                    <p className="text-sm text-gray-600 mt-1">{tool.description}</p>
                  )}
                  {tool.endpoint && (
                    <p className="text-xs text-gray-500 mt-1">{tool.endpoint}</p>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  {tool.type === 'mcp' && (
                    <button
                      onClick={() => toggleCapabilities(tool)}
                      className={`p-2 ${expandedCaps === tool.id ? 'text-primary-600' : 'text-gray-400 hover:text-gray-600'}`}
                      title="Capabilities / per-tool allow list"
                    >
                      <Layers className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => handleTestTool(tool.id)}
                    className="p-2 text-gray-400 hover:text-gray-600"
                    title="Test Tool"
                  >
                    <Play className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => { setGatewayKeyInput(''); setEditingTool(editingTool?.id === tool.id ? null : tool); }}
                    className="p-2 text-gray-400 hover:text-gray-600"
                    title="Edit Tool"
                  >
                    <Settings className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteTool(tool.id)}
                    className="p-2 text-red-400 hover:text-red-600"
                    title="Delete Tool"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Edit Form */}
              {editingTool?.id === tool.id && (
                <div className="mt-4 pt-4 border-t border-gray-200">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Name</label>
                      <input
                        type="text"
                        value={editingTool.name}
                        onChange={(e) => setEditingTool({ ...editingTool, name: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Type</label>
                      <select
                        value={editingTool.type}
                        onChange={(e) => setEditingTool({ ...editingTool, type: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      >
                        <option value="mcp">MCP (SSE Endpoint)</option>
                        <option value="http">HTTP (MCP Endpoint)</option>
                      </select>
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                      <textarea
                        value={editingTool.description || ''}
                        onChange={(e) => setEditingTool({ ...editingTool, description: e.target.value })}
                        rows={2}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">Endpoint</label>
                      <input
                        type="text"
                        value={editingTool.endpoint || ''}
                        onChange={(e) => setEditingTool({ ...editingTool, endpoint: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                    <div className="flex items-center space-x-3">
                      <input
                        type="checkbox"
                        id={`enabled-${tool.id}`}
                        checked={editingTool.enabled}
                        onChange={(e) => setEditingTool({ ...editingTool, enabled: e.target.checked })}
                        className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                      />
                      <label htmlFor={`enabled-${tool.id}`} className="text-sm font-medium text-gray-700">
                        Enabled
                      </label>
                    </div>
                  </div>

                  {/* AI Gateway routing — MCP connectors only. When on, the
                      agent's MCP traffic for this connector routes through the
                      gateway so it can govern the connection. */}
                  {editingTool.type === 'mcp' && (
                    <div className="mt-4 pt-4 border-t border-gray-200 space-y-3">
                      <div className="flex items-center space-x-3">
                        <input
                          type="checkbox"
                          id={`gw-enabled-${tool.id}`}
                          checked={!!editingTool.gateway_enabled}
                          onChange={(e) => setEditingTool({ ...editingTool, gateway_enabled: e.target.checked })}
                          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <label htmlFor={`gw-enabled-${tool.id}`} className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
                          <Network className="w-4 h-4 text-purple-600" /> Route MCP connectivity via AI Gateway
                        </label>
                      </div>
                      {editingTool.gateway_enabled && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pl-7">
                          <div className="md:col-span-2">
                            <label className="block text-sm font-medium text-gray-700 mb-2">Gateway MCP route URL</label>
                            <input
                              type="text"
                              value={editingTool.gateway_url || ''}
                              onChange={(e) => setEditingTool({ ...editingTool, gateway_url: e.target.value })}
                              placeholder="https://kong.example.com/mcp/filesystem"
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                            <p className="text-xs text-gray-500 mt-1">The gateway route that fronts this MCP server. Discovery + tool calls connect here instead of the endpoint above.</p>
                          </div>
                          <div className="md:col-span-2">
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                              Gateway API key {editingTool.gateway_api_key_set && <span className="text-green-600 font-normal">(key stored — leave blank to keep)</span>}
                            </label>
                            <input
                              type="password"
                              value={gatewayKeyInput}
                              onChange={(e) => setGatewayKeyInput(e.target.value)}
                              placeholder={editingTool.gateway_api_key_set ? '••••••••' : 'sent via the apikey header (Kong key-auth)'}
                              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex justify-end space-x-2 mt-4">
                    <button
                      onClick={() => { setGatewayKeyInput(''); setEditingTool(null); }}
                      className="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => handleUpdateTool(editingTool)}
                      className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                    >
                      Save Changes
                    </button>
                  </div>
                </div>
              )}

              {/* Test Result */}
              {testResults[tool.id] && (
                <div className="mt-4 pt-4 border-t border-gray-200">
                  <h4 className="text-sm font-medium text-gray-900 mb-2">Test Result</h4>
                  <pre className="bg-gray-100 p-3 rounded text-xs overflow-x-auto">
                    {JSON.stringify(testResults[tool.id], null, 2)}
                  </pre>
                </div>
              )}

              {/* Capability browser — only meaningful for MCP servers, and
                  only after a successful test/discovery. */}
              {expandedCaps === tool.id && tool.type === 'mcp' && (
                <CapabilityPanel
                  toolId={tool.id}
                  loading={!!capsLoading[tool.id]}
                  error={capsError[tool.id]}
                  caps={capsByTool[tool.id]}
                  onToggleTool={(name, disabled) => handleToggleDiscoveredTool(tool.id, name, disabled)}
                  onRefresh={() => loadCapabilities(tool.id)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {filteredTools.length === 0 && !isLoading && (
        <div className="text-center py-8">
          <p className="text-gray-500">No tools found</p>
        </div>
      )}
    </div>
  );
};

interface CapabilityPanelProps {
  toolId: number;
  loading: boolean;
  error?: string;
  caps: ToolCapabilities | null | undefined;
  onToggleTool: (mcpName: string, nextDisabled: boolean) => void;
  onRefresh: () => void;
}

const CapabilityPanel: React.FC<CapabilityPanelProps> = ({ loading, error, caps, onToggleTool, onRefresh }) => {
  if (loading) {
    return (
      <div className="mt-4 pt-4 border-t border-gray-200 text-sm text-gray-500">
        Loading capabilities…
      </div>
    );
  }
  if (error) {
    return (
      <div className="mt-4 pt-4 border-t border-gray-200 text-sm text-red-600">
        {error}
      </div>
    );
  }
  if (!caps) return null;
  const discovered: DiscoveredMcpTool[] = caps.tools || [];
  const enabledCount = discovered.filter(t => !t.disabled).length;

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h4 className="text-sm font-medium text-gray-900">Capabilities</h4>
          <p className="text-xs text-gray-500 mt-0.5">
            {discovered.length > 0
              ? `${enabledCount}/${discovered.length} tools exposed to the agent. Uncheck to hide one from the LLM.`
              : caps.message || 'No tools discovered yet — click the play button to run discovery.'}
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50"
          title="Refresh capability list"
        >
          Refresh
        </button>
      </div>

      {discovered.length > 0 && (
        <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
          {discovered.map(t => (
            <label
              key={t.name}
              className={`flex items-start space-x-2 p-2 rounded border ${
                t.disabled ? 'bg-gray-50 border-gray-200' : 'bg-white border-gray-200'
              } hover:bg-gray-50 cursor-pointer`}
            >
              <input
                type="checkbox"
                checked={!t.disabled}
                onChange={(e) => onToggleTool(t.name, !e.target.checked)}
                className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center space-x-2">
                  <code className={`text-xs font-mono ${t.disabled ? 'text-gray-400 line-through' : 'text-gray-800'}`}>
                    {t.name}
                  </code>
                  {t.disabled && (
                    <span className="px-1.5 py-0.5 text-[10px] uppercase tracking-wide bg-red-100 text-red-700 rounded">
                      blocked
                    </span>
                  )}
                </div>
                {t.description && (
                  <p className={`text-xs mt-0.5 ${t.disabled ? 'text-gray-400' : 'text-gray-600'}`}>
                    {t.description}
                  </p>
                )}
              </div>
            </label>
          ))}
        </div>
      )}
    </div>
  );
};

export default ToolManager;


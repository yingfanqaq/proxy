import React, { useState, useMemo } from 'react';
import { X, Settings, Database, Info, Activity, ShieldCheck, Server, Terminal, AlertTriangle, Copy } from 'lucide-react';

const CLASS_OPTIONS = {
  input: ['Codex Proxy', 'Claude Proxy', 'Gemini Proxy', 'OpenAI API', 'Claude API', 'Gemini API', 'DeepSeek API', 'Custom API'],
  transform: ['LiteLLM'],
  output: ['OpenAI Output', 'Anthropic Output', 'Gemini Output']
};

function CurlBlock({ label, command }: { label: string; command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border-main)] bg-[var(--text-primary)]/[0.03]">
        <span className="text-[9px] font-black text-[var(--text-secondary)] uppercase tracking-tighter">{label}</span>
        <button
          onClick={() => { navigator.clipboard.writeText(command); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
          className="text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
          title="Copy"
        >
          {copied ? <span className="text-[9px] text-green-500 font-bold">Copied</span> : <Copy size={11} />}
        </button>
      </div>
      <pre className="px-3 py-2 text-[10px] text-[var(--text-primary)] font-mono leading-relaxed whitespace-pre-wrap break-all select-all">{command}</pre>
    </div>
  );
}

export const Inspector = ({
  selectedNode,
  onUpdateNode,
  onClose,
  onTestNode,
  allNodes,
  allEdges,
  onRefreshMapping,
}: {
  selectedNode: any,
  onUpdateNode: (id: string, data: any) => void,
  onClose: () => void,
  onTestNode: (id: string) => void,
  allNodes?: any[],
  allEdges?: any[],
  onRefreshMapping?: (id: string) => void,
}) => {
  const [testing, setTesting] = useState(false);

  if (!selectedNode) return null;

  const { data, id, type } = selectedNode;

  const handleTest = async () => {
    setTesting(true);
    await onTestNode(id);
    setTesting(false);
  };

  const handleClassChange = (newClass: string) => {
    const isProxy = newClass.toLowerCase().includes('proxy');
    const subtype = isProxy ? 'proxy' : 'api';
    let protocol = data.protocol;
    if (newClass.includes('OpenAI')) protocol = 'OpenAI';
    if (newClass.includes('Anthropic') || newClass.includes('Claude')) protocol = 'Anthropic';
    if (newClass.includes('Gemini')) protocol = 'Gemini';
    onUpdateNode(id, { ...data, className: newClass, subtype, protocol });
  };

  const conflictingProxyPorts = useMemo(() => {
    if (!allNodes) return new Set<number>();
    const provider = String(data.provider || data.className || data.label || '').toLowerCase();
    return new Set(
      allNodes
        .filter(n => {
          if (n.id === id || n.type !== 'input' || n.data.subtype !== 'proxy' || !n.data.port) return false;
          const otherProvider = String(n.data.provider || n.data.className || n.data.label || '').toLowerCase();
          return otherProvider !== provider;
        })
        .map(n => Number(n.data.port))
    );
  }, [allNodes, id]);

  const currentPort = Number(data.port) || 0;
  const portConflict = type === 'input' && data.subtype === 'proxy' && currentPort > 0 && conflictingProxyPorts.has(currentPort);

  const portInput = (label: string, accent?: boolean) => (
    <div>
      <label className={`block text-[10px] font-bold mb-1 uppercase tracking-tighter ${accent ? 'text-[var(--accent)] font-black' : 'text-[var(--text-secondary)]'}`}>{label}</label>
      <div className="relative">
        {!accent && <Server size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />}
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={data.port || ''}
          onChange={(e) => {
            const val = e.target.value.replace(/\D/g, '');
            onUpdateNode(id, { ...data, port: val ? parseInt(val) : '' });
          }}
          placeholder="39121"
          className={`w-full bg-[var(--bg-main)] border rounded-lg ${accent ? 'px-3' : 'pl-9 pr-3'} py-2 text-xs text-[var(--text-primary)] focus:outline-none font-mono font-bold transition-all shadow-sm ${
            portConflict ? 'border-red-500 focus:border-red-500' : accent ? 'border-[var(--accent)]/30 focus:border-[var(--accent)]' : 'border-[var(--border-main)] focus:border-[var(--accent)]'
          }`}
        />
      </div>
      {portConflict && (
        <div className="flex items-center gap-1.5 mt-1.5 text-red-400">
          <AlertTriangle size={11} />
          <span className="text-[10px] font-bold">Port {currentPort} is already used by another node</span>
        </div>
      )}
    </div>
  );

  const provider = data.provider || '';
  const protocol = (data.protocol || data.format || 'OpenAI').toLowerCase();

  const outputModels = useMemo(() => {
    if (type !== 'output' || !allNodes || !allEdges) return [];
    const upstreamTransforms = allEdges
      .filter(e => e.target === id)
      .map(e => allNodes.find(n => n.id === e.source && n.type === 'transform'))
      .filter(Boolean);
    const models: string[] = [];
    for (const transform of upstreamTransforms) {
      try {
        const mapping = typeof transform.data.mapping === 'string'
          ? JSON.parse(transform.data.mapping)
          : transform.data.mapping;
        models.push(...Object.keys(mapping || {}));
      } catch {}
    }
    return [...new Set(models)];
  }, [allNodes, allEdges, id, type]);

  const outputModel = useMemo(() => {
    if (outputModels.length === 0) return 'MODEL_FROM_LIST';
    const preferred = protocol.includes('anthropic')
      ? ['claude-code', 'claude-code-sonnet', 'sonnet', 'claude-code-opus', 'opus', 'claude-code-haiku', 'haiku', 'claude-code-opus-4-7', 'claude-code-opus-4-7-high', 'claude-code-opus-4-7-xhigh', 'claude-code-opus-4-6', 'claude-code-opus-4-6-high', 'claude-code-sonnet-4-6', 'claude-code-sonnet-4-6-high']
      : protocol.includes('gemini')
      ? ['gemini', 'gemini-3.1-pro-preview', 'gemini-2.5-pro', 'gemini-2.5-flash']
      : ['codex', 'gpt-5.5', 'gpt-5.4', 'gpt-5.3-codex', 'gpt-5.2'];
    return preferred.find(model => outputModels.includes(model)) || outputModels[0];
  }, [outputModels, protocol]);

  const curlBase = type === 'output'
    ? `http://127.0.0.1:${data.port || '???'}`
    : data.subtype === 'proxy'
    ? `http://127.0.0.1:${data.port || '???'}`
    : (data.baseUrl || 'http://127.0.0.1:4000');

  const PROXY_KEYS: Record<string, string> = {
    codex: 'codex-proxy-local-key',
    gemini: 'gemini-proxy-local-key',
    claude: 'claude-proxy-local-key',
  };
  const curlKey = type === 'output'
    ? (data.apiKey || 'litellm-local-test-key')
    : (data.apiKey || PROXY_KEYS[provider] || 'YOUR_API_KEY');

  function curlCommands(): { label: string; command: string }[] {
    if (type === 'output') {
      if (protocol.includes('anthropic')) {
        return [
          {
            label: 'List Models',
            command: `curl ${curlBase}/v1/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
          },
          {
            label: 'Test Messages (Anthropic)',
            command: `curl ${curlBase}/v1/messages \\\n  -H "Content-Type: application/json" \\\n  -H "x-api-key: ${curlKey}" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -d '{"model": "${outputModel}", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}'`,
          },
        ];
      }
      if (protocol.includes('gemini')) {
        return [
          {
            label: 'List Models',
            command: `curl ${curlBase}/v1/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
          },
          {
            label: 'Test Chat Completion',
            command: `curl ${curlBase}/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${curlKey}" \\\n  -d '{"model": "${outputModel}", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}'`,
          },
        ];
      }
      return [
        {
          label: 'List Models',
          command: `curl ${curlBase}/v1/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
        },
        {
          label: 'Test Chat Completion',
          command: `curl ${curlBase}/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${curlKey}" \\\n  -d '{"model": "${outputModel}", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}'`,
        },
      ];
    }
    if (protocol.includes('anthropic') || provider === 'claude') {
      return [
        {
          label: 'List Models',
          command: `curl ${curlBase}/v1/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
        },
        {
          label: 'Test Messages (Anthropic)',
          command: `curl ${curlBase}/v1/messages \\\n  -H "Content-Type: application/json" \\\n  -H "x-api-key: ${curlKey}" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -d '{"model": "claude-code", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}'`,
        },
      ];
    }
    if (protocol.includes('gemini') || provider === 'gemini') {
      return [
        {
          label: 'List Models',
          command: `curl ${curlBase}/v1beta/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
        },
        {
          label: 'Test Generate (Gemini)',
          command: `curl "${curlBase}/v1beta/models/gemini-2.5-flash:generateContent" \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${curlKey}" \\\n  -d '{"contents": [{"parts": [{"text": "hi"}]}]}'`,
        },
      ];
    }
    return [
      {
        label: 'List Models',
        command: `curl ${curlBase}/v1/models \\\n  -H "Authorization: Bearer ${curlKey}"`,
      },
      {
        label: 'Test Chat Completion (OpenAI)',
        command: `curl ${curlBase}/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer ${curlKey}" \\\n  -d '{"model": "test", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}'`,
      },
    ];
  }

  return (
    <aside className="w-80 bg-[var(--bg-sidebar)] border-l border-[var(--border-main)] flex flex-col h-full shadow-2xl select-none animate-in slide-in-from-right duration-200 transition-colors duration-300">
      <div className="p-4 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--text-primary)]/[0.03]">
        <div className="flex items-center gap-2">
          <Settings size={16} className="text-[var(--accent)]" />
          <h2 className="text-sm font-bold text-[var(--text-primary)]">Node Configuration</h2>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-[var(--text-primary)]/[0.05] rounded-lg transition-colors text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-6 scrollbar-thin">
        {/* METADATA */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Info size={14} className="text-[var(--text-secondary)]" />
            <h3 className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-widest">Metadata</h3>
          </div>
          <div className="space-y-3 bg-[var(--text-primary)]/[0.02] p-3 rounded-xl border border-[var(--border-main)]">
            <div>
              <label className="block text-[9px] font-black text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Node ID</label>
              <div className="text-[11px] text-[var(--text-secondary)] font-mono bg-[var(--text-primary)]/[0.05] px-2 py-1 rounded-md truncate border border-[var(--border-main)]">{id}</div>
            </div>
            <div>
              <label className="block text-[9px] font-black text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Class</label>
              <select value={data.className} onChange={(e) => handleClassChange(e.target.value)}
                className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] font-bold transition-all shadow-sm">
                {CLASS_OPTIONS[type as keyof typeof CLASS_OPTIONS]?.map(opt => (<option key={opt} value={opt}>{opt}</option>))}
              </select>
            </div>
            <div>
              <label className="block text-[9px] font-black text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Name</label>
              <input type="text" value={data.label} onChange={(e) => onUpdateNode(id, { ...data, label: e.target.value })}
                className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] transition-all shadow-sm" />
            </div>
          </div>
        </section>

        {/* PARAMETERS */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Database size={14} className="text-[var(--text-secondary)]" />
            <h3 className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-widest">Parameters</h3>
          </div>
          <div className="space-y-4">
            {type === 'input' && (
              <>
                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="bg-[var(--text-primary)]/[0.02] p-3 rounded-xl border border-[var(--border-main)] flex flex-col gap-1">
                    <span className="text-[9px] font-black text-[var(--text-secondary)] uppercase tracking-tighter">Status</span>
                    <div className="flex items-center gap-1.5">
                      <div className={`w-2 h-2 rounded-full ${data.status === 'online' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.4)]'}`} />
                      <span className={`text-[11px] font-black ${data.status === 'online' ? 'text-green-500' : 'text-red-500 uppercase'}`}>{data.status === 'online' ? 'Online' : 'Offline'}</span>
                    </div>
                  </div>
                  <button onClick={handleTest} disabled={testing}
                    className="bg-[var(--text-primary)]/[0.05] hover:bg-[var(--text-primary)]/[0.1] border border-[var(--border-main)] rounded-xl flex flex-col items-center justify-center gap-1 transition-all active:scale-95 disabled:opacity-50">
                    <Activity size={14} className={testing ? "animate-spin text-[var(--accent)]" : "text-[var(--text-secondary)]"} />
                    <span className="text-[9px] font-black text-[var(--text-secondary)] uppercase tracking-tighter">Test Link</span>
                  </button>
                </div>

                {data.subtype === 'api' ? (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Base URL</label>
                      <input type="text" value={data.baseUrl || ''} onChange={(e) => onUpdateNode(id, { ...data, baseUrl: e.target.value })}
                        placeholder="https://api.openai.com/v1"
                        className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-3 py-2 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] transition-all shadow-sm" />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">API Key</label>
                      <div className="relative">
                        <ShieldCheck size={12} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                        <input type="password" value={data.apiKey || ''} onChange={(e) => onUpdateNode(id, { ...data, apiKey: e.target.value })}
                          placeholder="sk-..."
                          className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-3 py-2 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] pr-8 transition-all shadow-sm" />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {portInput('Proxy Port')}
                    <div>
                      <label className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Proxy API Key</label>
                      <div className="relative">
                        <ShieldCheck size={12} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                        <input type="text" value={data.apiKey || PROXY_KEYS[provider] || ''} onChange={(e) => onUpdateNode(id, { ...data, apiKey: e.target.value })}
                          className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-3 py-2 text-[11px] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] pr-8 transition-all shadow-sm" />
                      </div>
                      <p className="text-[9px] text-[var(--text-secondary)] mt-1 italic">Key used to authenticate with this proxy service.</p>
                    </div>
                  </div>
                )}
              </>
            )}

            {type === 'transform' && (
              <div className="space-y-4">
                <button
                  onClick={() => onRefreshMapping?.(id)}
                  className="w-full bg-[var(--text-primary)]/[0.05] hover:bg-[var(--text-primary)]/[0.1] border border-[var(--border-main)] rounded-xl px-3 py-2 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-tighter transition-all active:scale-95"
                >
                  Refresh Mapping From Inputs
                </button>
                <div>
                  <label className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Model Mapping (JSON)</label>
                  <textarea rows={12} value={data.mapping || ''} onChange={(e) => onUpdateNode(id, { ...data, mapping: e.target.value })}
                    placeholder='{"model-name": "upstream-model-name"}'
                    className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-3 py-2 text-[11px] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] resize-none scrollbar-thin transition-all shadow-sm" />
                  <p className="text-[9px] text-[var(--text-secondary)] mt-1 italic">Key = client model name, Value = upstream model name. Duplicate upstream names from different sources get source prefixes.</p>
                </div>
              </div>
            )}

            {type === 'output' && (
              <div className="space-y-4">
                {portInput('Active Port', true)}
                <div>
                  <label className="block text-[10px] font-bold text-[var(--text-secondary)] mb-1 uppercase tracking-tighter">Output API Key</label>
                  <div className="relative">
                    <ShieldCheck size={12} className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                    <input type="text" value={data.apiKey || ''} onChange={(e) => onUpdateNode(id, { ...data, apiKey: e.target.value })}
                      placeholder="litellm-local-test-key"
                      className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-lg px-3 py-2 text-[11px] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent)] pr-8 transition-all shadow-sm" />
                  </div>
                  <p className="text-[9px] text-[var(--text-secondary)] mt-1 italic">Clients use this key to access the output endpoint.</p>
                </div>
                <div className="p-3 bg-[var(--text-primary)]/[0.02] border border-[var(--border-main)] rounded-xl flex flex-col gap-2 shadow-inner">
                  <div className="flex items-center gap-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                    <span className="text-[9px] font-black text-[var(--text-secondary)] uppercase">Endpoint Logic</span>
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] leading-relaxed italic font-medium">
                    This output node exposes your aggregated AI services at <code className="text-blue-500 font-bold">localhost:{data.port}</code>.
                    The HOST is system-locked to loopback for security.
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* CURL COMMANDS */}
        {(type === 'input' || type === 'output') && (
          <section>
            <div className="flex items-center gap-2 mb-3">
              <Terminal size={14} className="text-[var(--text-secondary)]" />
              <h3 className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-widest">Quick Test</h3>
            </div>
            <div className="space-y-3">
              {curlCommands().map((cmd, i) => (
                <CurlBlock key={i} label={cmd.label} command={cmd.command} />
              ))}
            </div>
          </section>
        )}
      </div>

      <div className="p-4 border-t border-[var(--border-main)] bg-[var(--text-primary)]/[0.02]">
        <div className="flex items-center gap-2 text-[10px] text-[var(--text-secondary)] font-bold italic tracking-tighter">
          <Activity size={10} className="text-[var(--accent)]" />
          LIVE SYNC ACTIVE
        </div>
      </div>
    </aside>
  );
};

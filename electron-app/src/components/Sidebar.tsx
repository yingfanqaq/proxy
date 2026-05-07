import React, { useState } from 'react';
import { Play, Repeat, LogOut, Search, ChevronDown, ChevronRight, Zap, Globe, Cpu } from 'lucide-react';
import { clsx } from 'clsx';

const nodeCategories = [
  {
    category: 'Input Nodes',
    items: [
      { id: 'codex-proxy', label: 'Codex Proxy', type: 'input', subtype: 'proxy', provider: 'codex', protocol: 'Custom', port: 39121, icon: Cpu, className: 'Codex Proxy' },
      { id: 'claude-proxy', label: 'Claude Proxy', type: 'input', subtype: 'proxy', provider: 'claude', protocol: 'Anthropic', port: 39123, icon: Cpu, className: 'Claude Proxy' },
      { id: 'gemini-proxy', label: 'Gemini Proxy', type: 'input', subtype: 'proxy', provider: 'gemini', protocol: 'Gemini', port: 39122, icon: Cpu, className: 'Gemini Proxy' },
      { id: 'openai-api', label: 'OpenAI API', type: 'input', subtype: 'api', provider: 'openai', protocol: 'OpenAI', baseUrl: 'https://api.openai.com/v1', icon: Globe, className: 'OpenAI API' },
      { id: 'anthropic-api', label: 'Claude API', type: 'input', subtype: 'api', provider: 'anthropic', protocol: 'Claude API → Anthropic', adapter: 'claude-api-to-anthropic', baseUrl: 'https://api.anthropic.com', icon: Globe, className: 'Claude API' },
      { id: 'gemini-api', label: 'Gemini API', type: 'input', subtype: 'api', provider: 'gemini-api', protocol: 'Gemini', baseUrl: 'https://generativelanguage.googleapis.com', icon: Globe, className: 'Gemini API' },
      { id: 'deepseek-api', label: 'DeepSeek API', type: 'input', subtype: 'api', provider: 'deepseek', protocol: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', icon: Globe, className: 'DeepSeek API' },
      { id: 'custom-api', label: 'Custom API', type: 'input', subtype: 'api', provider: 'custom', protocol: 'Custom', baseUrl: '', icon: Zap, className: 'Custom API' },
    ]
  },
  {
    category: 'Transform Nodes',
    items: [
      { id: 'litellm', label: 'LiteLLM Transform', type: 'transform', icon: Repeat, className: 'LiteLLM' },
    ]
  },
  {
    category: 'Output Nodes',
    items: [
      { id: 'openai-output', label: 'OpenAI Output', type: 'output', protocol: 'OpenAI', icon: LogOut, className: 'OpenAI Output' },
      { id: 'anthropic-output', label: 'Anthropic Output', type: 'output', protocol: 'Anthropic', icon: LogOut, className: 'Anthropic Output' },
      { id: 'gemini-output', label: 'Gemini Output', type: 'output', protocol: 'Gemini', icon: LogOut, className: 'Gemini Output' },
    ]
  }
];

export const Sidebar = () => {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    'Input Nodes': true,
    'Transform Nodes': true,
    'Output Nodes': true,
  });

  const toggleCategory = (cat: string) => {
    setExpanded(prev => ({ ...prev, [cat]: !prev[cat] }));
  };

  const onDragStart = (event: React.DragEvent, nodeData: any) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(nodeData));
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <aside className="w-64 bg-[var(--bg-sidebar)] border-r border-[var(--border-main)] flex flex-col h-full select-none transition-colors duration-300">
      <div className="p-4 border-b border-[var(--border-main)]">
        <h2 className="text-sm font-bold text-[var(--text-secondary)] uppercase tracking-widest mb-4">Components</h2>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" size={14} />
          <input 
            type="text" 
            placeholder="Search nodes..." 
            className="w-full bg-[var(--bg-main)] border border-[var(--border-main)] rounded-xl py-2 pl-9 pr-4 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] transition-all"
          />
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-2 space-y-1 scrollbar-thin">
        {nodeCategories.map((group) => (
          <div key={group.category} className="mb-2">
            <button 
              onClick={() => toggleCategory(group.category)}
              className="w-full flex items-center justify-between px-3 py-2 hover:bg-[var(--text-primary)]/[0.05] rounded-lg transition-colors group"
            >
              <h3 className="text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">{group.category}</h3>
              {expanded[group.category] ? <ChevronDown size={14} className="text-[var(--text-secondary)]" /> : <ChevronRight size={14} className="text-[var(--text-secondary)]" />}
            </button>
            
            {expanded[group.category] && (
              <div className="mt-1 space-y-1 px-1">
                {group.items.map((node) => (
                  <div
                    key={node.id}
                    className="bg-[var(--bg-card)] border border-[var(--border-main)] rounded-xl p-3 cursor-grab hover:border-[var(--accent)] hover:shadow-lg transition-all flex items-center gap-3 group active:scale-95"
                    onDragStart={(event) => onDragStart(event, node)}
                    draggable
                  >
                    <div className={clsx(
                      "p-1.5 rounded-lg border border-[var(--border-main)] shadow-sm",
                      node.type === 'input' ? 'bg-blue-500/10 text-blue-500' : 
                      node.type === 'transform' ? 'bg-purple-500/10 text-purple-500' : 
                      'bg-green-500/10 text-green-500'
                    )}>
                      <node.icon size={13} />
                    </div>
                    <span className="text-xs font-bold text-[var(--text-primary)] transition-colors opacity-80 group-hover:opacity-100">
                      {node.label}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
};

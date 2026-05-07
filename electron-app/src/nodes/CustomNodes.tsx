import React, { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Repeat, LogOut, Settings2, Globe, Cpu, Zap } from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const HANDLE_CLASS = "!w-3 !h-3 !bg-[var(--text-secondary)] !border-2 !border-[var(--bg-card)] hover:!bg-[var(--accent)] transition-colors";

const BaseNode = ({ children, title, icon: Icon, selected, type, status }: { children: React.ReactNode, title: string, icon: any, selected?: boolean, type: string, status?: 'online' | 'offline' }) => {
  const iconColor = type === 'input' ? 'text-blue-500' : type === 'transform' ? 'text-purple-500' : 'text-green-500';
  const bgColor = type === 'input' ? 'bg-blue-500/10' : type === 'transform' ? 'bg-purple-500/10' : 'bg-green-500/10';

  return (
    <div className={cn(
      "w-[240px] bg-[var(--bg-card)] border rounded-xl overflow-hidden shadow-2xl transition-all duration-300 select-none",
      selected ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/30" : "border-[var(--border-main)]",
      "hover:border-[var(--text-secondary)]"
    )}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--text-primary)]/[0.03]">
        <div className="flex items-center gap-2.5">
          <div className={cn("p-1.5 rounded-lg border border-[var(--border-main)]", bgColor)}>
            <Icon size={14} className={cn("shrink-0", iconColor)} />
          </div>
          <div className="flex flex-col">
            <span className="text-[13px] font-bold text-[var(--text-primary)] tracking-tight leading-none mb-1">{title}</span>
            {status && (
              <div className="flex items-center gap-1">
                <div className={cn("w-1.5 h-1.5 rounded-full shadow-sm", status === 'online' ? "bg-green-500" : "bg-red-500")} />
                <span className="text-[9px] uppercase font-bold text-[var(--text-secondary)] tracking-tighter">{status}</span>
              </div>
            )}
          </div>
        </div>
        <Settings2 size={13} className="text-[var(--text-secondary)] cursor-pointer hover:text-[var(--text-primary)] transition-colors" />
      </div>

      {/* Body */}
      <div className="p-4 bg-[var(--bg-card)]">
        {children}
      </div>
    </div>
  );
};

export const InputNode = memo(({ data, selected }: NodeProps) => {
  const Icon = data.subtype === 'proxy' ? Cpu : (data.className === 'Custom API' ? Zap : Globe);
  return (
    <div className="relative w-[240px]">
      <BaseNode title={data.label || 'Input Node'} icon={Icon} selected={selected} type="input" status={data.status || 'offline'}>
        <div className="text-[11px] text-[var(--text-secondary)] flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <span className="font-medium">Protocol:</span>
            <span className="text-blue-500 font-mono font-bold bg-blue-500/5 px-1.5 py-0.5 rounded border border-blue-500/10">{data.protocol || 'OpenAI'}</span>
          </div>
          {data.adapter && (
            <div className="flex justify-between items-center">
              <span className="font-medium">Adapter:</span>
              <span className="text-blue-500 font-mono font-bold bg-blue-500/5 px-1.5 py-0.5 rounded border border-blue-500/10">Anthropic</span>
            </div>
          )}
          {data.subtype === 'proxy' ? (
            <div className="flex justify-between items-center">
              <span className="font-medium">Port:</span>
              <span className="text-[var(--text-primary)] font-mono font-bold">{data.port || '---'}</span>
            </div>
          ) : (
            <div className="flex justify-between items-center">
              <span className="font-medium">Endpoint:</span>
              <span className="text-[var(--text-primary)] truncate max-w-[110px] text-right font-mono" title={data.baseUrl}>{data.baseUrl ? new URL(data.baseUrl).hostname : 'API'}</span>
            </div>
          )}
        </div>
      </BaseNode>
      <Handle type="source" position={Position.Right} className={cn(HANDLE_CLASS, "!right-[-6px]")} />
    </div>
  );
});

export const TransformNode = memo(({ data, selected }: NodeProps) => {
  return (
    <div className="relative w-[240px]">
      <Handle type="target" position={Position.Left} className={cn(HANDLE_CLASS, "!left-[-6px]")} />
      <BaseNode title={data.label || 'Transform'} icon={Repeat} selected={selected} type="transform">
        <div className="text-[11px] text-[var(--text-secondary)] flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <span className="font-medium">Engine:</span>
            <span className="text-purple-500 font-mono font-bold bg-purple-500/5 px-1.5 py-0.5 rounded border border-purple-500/10">{data.className || 'LiteLLM'}</span>
          </div>
        </div>
      </BaseNode>
      <Handle type="source" position={Position.Right} className={cn(HANDLE_CLASS, "!right-[-6px]")} />
    </div>
  );
});

export const OutputNode = memo(({ data, selected }: NodeProps) => {
  return (
    <div className="relative w-[240px]">
      <Handle type="target" position={Position.Left} className={cn(HANDLE_CLASS, "!left-[-6px]")} />
      <BaseNode title={data.label || 'Output Node'} icon={LogOut} selected={selected} type="output">
        <div className="text-[11px] text-[var(--text-secondary)] flex flex-col gap-2.5">
          <div className="flex justify-between items-center">
            <span className="font-medium">Listen:</span>
            <span className="text-green-500 font-mono font-bold">127.0.0.1:{data.port || 1234}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="font-medium">Format:</span>
            <span className="text-[var(--text-primary)] font-mono">{data.protocol || 'OpenAI'}</span>
          </div>
        </div>
      </BaseNode>
    </div>
  );
});

import React, { useState, useCallback, useRef, useEffect } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Connection,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { Sidebar } from './components/Sidebar';
import { Inspector } from './components/Inspector';
import { InputNode, TransformNode, OutputNode } from './nodes/CustomNodes';
import { Save, Zap, Settings, Plus, LayoutGrid, ChevronDown, Terminal, Trash2, CheckCircle2, ShieldAlert, Loader2, Sun, Moon, Play, Square, RotateCcw, Copy, Pencil, FileText, Trash } from 'lucide-react';
import { clsx } from 'clsx';
import * as api from './api';

const nodeTypes = {
  input: InputNode,
  transform: TransformNode,
  output: OutputNode,
};

interface Log {
  id: string;
  timestamp: string;
  message: string;
  type: 'info' | 'success' | 'error' | 'warn';
}

interface Scheme {
  id: string;
  name: string;
  nodes: Node[];
  edges: Edge[];
}

type GraphSnapshot = {
  nodes: Node[];
  edges: Edge[];
};

const PROVIDER_LABELS: Record<string, string> = {
  codex: 'Codex Proxy',
  gemini: 'Gemini Proxy',
  claude: 'Claude Proxy',
};

const FORMAT_LABELS: Record<string, string> = {
  openai: 'OpenAI Output',
  anthropic: 'Anthropic Output',
  gemini: 'Gemini Output',
};

const edgeStyle = {
  stroke: 'var(--accent)',
  strokeWidth: 2,
};
const edgeMarker = {
  type: MarkerType.ArrowClosed,
  color: 'var(--accent)',
};

const LOCAL_PROVIDER_PORTS: Record<string, number> = {
  codex: 39121,
  gemini: 39122,
  claude: 39123,
};
const LOCAL_PROVIDER_CONFIG_KEYS: Record<string, string> = {
  codex: 'codex_port',
  gemini: 'gemini_port',
  claude: 'claude_port',
};

const FALLBACK_PROXY_MODELS: Record<string, string[]> = {
  codex: ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'],
  gemini: ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
  claude: ['claude-code', 'claude-code-sonnet', 'claude-code-opus', 'claude-code-haiku', 'claude-code-sonnet-4-6', 'claude-code-sonnet-4-6-high', 'claude-code-opus-4-7', 'claude-code-opus-4-7-high', 'claude-code-opus-4-7-xhigh', 'claude-code-opus-4-6', 'claude-code-opus-4-6-max', 'claude-code-haiku-4-5', 'sonnet', 'opus', 'haiku'],
};

const PROVIDER_PROTOCOLS: Record<string, string> = {
  codex: 'Custom',
  gemini: 'Gemini',
  claude: 'Anthropic',
};

const EXTERNAL_FORMAT_LABELS: Record<string, string> = {
  openai: 'OpenAI API',
  anthropic: 'Claude Code API',
  gemini: 'Gemini API',
  deepseek: 'DeepSeek API',
  custom: 'Custom API',
};

const EXTERNAL_PROVIDER_PREFIX: Record<string, string> = {
  openai: 'openai-api',
  anthropic: 'claude-api',
  gemini: 'gemini-api',
  deepseek: 'deepseek-api',
  custom: 'custom-api',
};

type SourceDescriptor = {
  key: string;
  label: string;
  prefix: string;
  provider: string;
  subtype: 'proxy' | 'api';
  baseUrl?: string;
  adapter?: string;
};

type ModelSource = {
  sourceKey: string;
  sourceLabel: string;
  upstream: string;
  effort?: string;
};

type ModelAlias = {
  alias: string;
  upstream: string;
  effort?: string;
};

const CLAUDE_EFFORT_LEVELS = ['low', 'medium', 'high', 'xhigh', 'max'];
const CLAUDE_CODE_UPSTREAM_MODELS = new Set(['claude-sonnet-4-6', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-haiku-4-5']);
const CLAUDE_CODE_MODEL_ALIASES: ModelAlias[] = [
  { alias: 'claude-code', upstream: 'claude-sonnet-4-6' },
  { alias: 'claude-code-sonnet', upstream: 'claude-sonnet-4-6' },
  { alias: 'claude-code-opus', upstream: 'claude-opus-4-7' },
  { alias: 'claude-code-haiku', upstream: 'claude-haiku-4-5' },
  { alias: 'sonnet', upstream: 'claude-sonnet-4-6' },
  { alias: 'opus', upstream: 'claude-opus-4-7' },
  { alias: 'haiku', upstream: 'claude-haiku-4-5' },
  { alias: 'claude-code-sonnet-4-6', upstream: 'claude-sonnet-4-6' },
  { alias: 'claude-code-opus-4-7', upstream: 'claude-opus-4-7' },
  { alias: 'claude-code-opus-4-6', upstream: 'claude-opus-4-6' },
  { alias: 'claude-code-haiku-4-5', upstream: 'claude-haiku-4-5' },
  { alias: 'claude-sonnet-4-6', upstream: 'claude-sonnet-4-6' },
  { alias: 'claude-opus-4-7', upstream: 'claude-opus-4-7' },
  { alias: 'claude-opus-4-6', upstream: 'claude-opus-4-6' },
  { alias: 'claude-haiku-4-5', upstream: 'claude-haiku-4-5' },
  ...['low', 'medium', 'high'].flatMap(effort => [
    { alias: `claude-code-sonnet-${effort}`, upstream: 'claude-sonnet-4-6', effort },
    { alias: `claude-code-sonnet-4-6-${effort}`, upstream: 'claude-sonnet-4-6', effort },
  ]),
  ...['low', 'medium', 'high', 'xhigh'].flatMap(effort => [
    { alias: `claude-code-opus-${effort}`, upstream: 'claude-opus-4-7', effort },
    { alias: `claude-code-opus-4-7-${effort}`, upstream: 'claude-opus-4-7', effort },
  ]),
  ...['low', 'medium', 'high', 'max'].flatMap(effort => [
    { alias: `claude-code-opus-4-6-${effort}`, upstream: 'claude-opus-4-6', effort },
  ]),
];

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'source';
}

function normalizeBaseUrl(value: string | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    const pathname = parsed.pathname.replace(/\/+$/, '');
    return `${parsed.protocol.toLowerCase()}//${parsed.host.toLowerCase()}${pathname}`;
  } catch {
    return raw.replace(/\/+$/, '').toLowerCase();
  }
}

function formatFromProtocol(protocol: string | undefined): string {
  const text = String(protocol || 'openai').toLowerCase();
  if (text.includes('anthropic') || text.includes('claude')) return 'anthropic';
  if (text.includes('gemini')) return 'gemini';
  if (text.includes('deepseek')) return 'openai';
  return 'openai';
}

function configuredLocalPort(config: Record<string, any> | undefined, provider: string, runtimePort?: number): number {
  const configKey = LOCAL_PROVIDER_CONFIG_KEYS[provider];
  const configured = configKey ? Number(config?.[configKey]) : 0;
  if (Number.isInteger(configured) && configured > 0) return configured;
  const runtime = Number(runtimePort);
  if (Number.isInteger(runtime) && runtime > 0) return runtime;
  return LOCAL_PROVIDER_PORTS[provider] || 0;
}

function inferLocalProvider(data: any): string {
  const raw = String(data.provider || '').toLowerCase();
  if (raw in LOCAL_PROVIDER_PORTS) return raw;
  const text = `${raw} ${data.className || ''} ${data.label || ''}`.toLowerCase();
  if (text.includes('codex')) return 'codex';
  if (text.includes('claude')) return 'claude';
  if (text.includes('gemini')) return 'gemini';
  return slug(data.className || data.label || raw || 'custom');
}

function inferApiProvider(data: any): string {
  const raw = String(data.provider || '').toLowerCase();
  const text = `${raw} ${data.className || ''} ${data.label || ''} ${data.protocol || ''}`.toLowerCase();
  if (raw === 'custom' || text.includes('custom api')) return 'custom';
  if (raw === 'anthropic' || raw === 'claude-api' || text.includes('claude code api') || text.includes('claude api') || text.includes('anthropic')) return 'anthropic';
  if (raw === 'gemini' || raw === 'gemini-api' || text.includes('gemini')) return 'gemini';
  if (raw === 'deepseek' || text.includes('deepseek')) return 'deepseek';
  if (raw === 'openai' || text.includes('openai')) return 'openai';
  return formatFromProtocol(data.protocol);
}

function descriptorFromFlow(flow: any): SourceDescriptor {
  const source = flow.source || {};
  if (source.kind === 'external') {
    const format = source.format || 'openai';
    const baseUrl = normalizeBaseUrl(source.base_url || source.baseUrl);
    const label = EXTERNAL_FORMAT_LABELS[format] || `${format} API`;
    const prefix = EXTERNAL_PROVIDER_PREFIX[format] || slug(label);
    const key = format === 'custom' ? `api:custom:${baseUrl}` : `api:${format}`;
    const adapter = source.adapter || (format === 'anthropic' ? 'claude-code-api-to-anthropic' : undefined);
    return { key, label, prefix, provider: format, subtype: 'api', baseUrl, adapter };
  }
  const provider = source.provider || 'codex';
  return {
    key: `proxy:${provider}`,
    label: PROVIDER_LABELS[provider] || `${provider} Proxy`,
    prefix: slug(provider),
    provider,
    subtype: 'proxy',
  };
}

function descriptorFromNode(node: Node): SourceDescriptor {
  const data = node.data || {};
  const subtype = data.subtype === 'api' ? 'api' : 'proxy';
  if (subtype === 'api') {
    const provider = inferApiProvider(data);
    const baseUrl = normalizeBaseUrl(data.baseUrl || data.base_url);
    const isCustom = data.className === 'Custom API' || provider === 'custom';
    const label = data.className || data.label || EXTERNAL_FORMAT_LABELS[provider] || `${provider} API`;
    const prefix = isCustom ? 'custom-api' : (EXTERNAL_PROVIDER_PREFIX[provider] || slug(label));
    const key = isCustom ? `api:custom:${baseUrl}` : `api:${provider}`;
    const adapter = data.adapter || (provider === 'anthropic' ? 'claude-code-api-to-anthropic' : undefined);
    return { key, label, prefix, provider, subtype, baseUrl, adapter };
  }
  const provider = inferLocalProvider(data);
  const label = data.className || data.label || PROVIDER_LABELS[provider] || `${provider} Proxy`;
  return { key: `proxy:${provider}`, label, prefix: slug(provider), provider, subtype };
}

function serviceNameForInput(node: Node): string | null {
  const desc = descriptorFromNode(node);
  return desc.subtype === 'proxy' && desc.provider in LOCAL_PROVIDER_PORTS ? desc.provider : null;
}

function serviceNameForData(data: any): string | null {
  if (data?.subtype !== 'proxy') return null;
  const provider = inferLocalProvider(data);
  return provider in LOCAL_PROVIDER_PORTS ? provider : null;
}

function outputFormatFromNode(node: Node): string {
  const data = node.data || {};
  if (data.format) return String(data.format).toLowerCase();
  return formatFromProtocol(data.protocol);
}

function parseMapping(mapping: unknown): Record<string, string> {
  if (!mapping) return {};
  if (typeof mapping === 'object' && !Array.isArray(mapping)) return mapping as Record<string, string>;
  if (typeof mapping !== 'string' || !mapping.trim()) return {};
  const parsed = JSON.parse(mapping);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
  return parsed as Record<string, string>;
}

function addModelAlias(
  mapping: Record<string, string>,
  sources: Record<string, ModelSource>,
  desc: SourceDescriptor,
  alias: string,
  upstream: string,
  effort?: string,
): string {
  let candidate = alias;
  const existing = sources[candidate];
  if (
    Object.prototype.hasOwnProperty.call(mapping, candidate)
    && !existing
    && String(mapping[candidate] || '').trim() === upstream
  ) {
    sources[candidate] = { sourceKey: desc.key, sourceLabel: desc.label, upstream, effort };
    return candidate;
  }
  if (
    Object.prototype.hasOwnProperty.call(mapping, candidate)
    && (!existing || existing.sourceKey !== desc.key)
  ) {
    candidate = `${desc.prefix}-${alias}`;
  }
  let unique = candidate;
  let suffix = 2;
  while (
    Object.prototype.hasOwnProperty.call(mapping, unique)
    && (!sources[unique] || sources[unique].sourceKey !== desc.key)
  ) {
    unique = `${candidate}-${suffix++}`;
  }
  mapping[unique] = upstream;
  sources[unique] = { sourceKey: desc.key, sourceLabel: desc.label, upstream, effort };
  return unique;
}

function inferClaudeCodeAlias(alias: string): ModelAlias | null {
  const exact = CLAUDE_CODE_MODEL_ALIASES.find(item => item.alias === alias);
  if (exact) return exact;
  for (const effort of CLAUDE_EFFORT_LEVELS) {
    const suffix = `-${effort}`;
    if (!alias.endsWith(suffix)) continue;
    const base = alias.slice(0, -suffix.length);
    const baseAlias = CLAUDE_CODE_MODEL_ALIASES.find(item => item.alias === base && !item.effort);
    if (baseAlias && baseAlias.upstream !== 'claude-haiku-4-5') {
      return { alias, upstream: baseAlias.upstream, effort };
    }
  }
  if (CLAUDE_CODE_UPSTREAM_MODELS.has(alias)) return { alias, upstream: alias };
  return null;
}

function mergeFlowModels(flows: any[]): { mapping: Record<string, string>; sources: Record<string, ModelSource> } {
  const mapping: Record<string, string> = {};
  const sources: Record<string, ModelSource> = {};
  for (const flow of flows) {
    const desc = descriptorFromFlow(flow);
    for (const model of flow.models || []) {
      const alias = String(model.name || '').trim();
      const upstream = String(model.upstream || model.name || '').trim();
      const effort = String(model.effort || model.reasoning_effort || '').trim() || undefined;
      if (!alias || !upstream) continue;
      addModelAlias(mapping, sources, desc, alias, upstream, effort);
    }
  }
  return { mapping, sources };
}

function modelsForSource(mid: Node, source: Node, connectedInputs: Node[]): any[] {
  let mapping: Record<string, string> = {};
  try {
    mapping = parseMapping(mid.data?.mapping);
  } catch {
    return [];
  }
  const sourceMeta = (mid.data?.modelSources || {}) as Record<string, ModelSource>;
  const desc = descriptorFromNode(source);
  const hasMultipleInputs = connectedInputs.length > 1;
  const ownsUnscopedAliases = !hasMultipleInputs || connectedInputs[0]?.id === source.id;
  const models: any[] = [];

  for (const [name, upstreamValue] of Object.entries(mapping)) {
    const upstream = String(upstreamValue || '').trim();
    if (!name || !upstream) continue;
    const owner = sourceMeta[name];
    if (owner?.sourceKey === desc.key) {
      models.push({ name, upstream, ...(owner.effort ? { effort: owner.effort } : {}) });
      continue;
    }
    const inferred = desc.provider === 'anthropic' ? inferClaudeCodeAlias(name) : null;
    if (!owner && inferred) {
      models.push({ name, upstream: inferred.upstream, ...(inferred.effort ? { effort: inferred.effort } : {}) });
      continue;
    }
    if (!owner && name.startsWith(`${desc.prefix}-`)) {
      models.push({ name, upstream });
      continue;
    }
    if (!owner && ownsUnscopedAliases) {
      models.push({ name, upstream });
    }
  }
  return models;
}

function connectedInputNodes(transform: Node, allNodes: Node[], allEdges: Edge[]): Node[] {
  return allEdges
    .filter(e => e.target === transform.id)
    .map(e => allNodes.find(n => n.id === e.source && n.type === 'input'))
    .filter((node): node is Node => Boolean(node));
}

function connectedOutputNodes(transform: Node, allNodes: Node[], allEdges: Edge[]): Node[] {
  return allEdges
    .filter(e => e.source === transform.id)
    .map(e => allNodes.find(n => n.id === e.target && n.type === 'output'))
    .filter((node): node is Node => Boolean(node));
}

function duplicateInputIssue(source: Node, transform: Node, allNodes: Node[], allEdges: Edge[]): string | null {
  const incoming = connectedInputNodes(transform, allNodes, allEdges);
  const sourceDesc = descriptorFromNode(source);
  if (sourceDesc.subtype === 'api' && sourceDesc.provider === 'custom' && !sourceDesc.baseUrl) {
    return 'Rejected: Custom API must have a Base URL before connecting.';
  }
  for (const existing of incoming) {
    if (existing.id === source.id) continue;
    const existingDesc = descriptorFromNode(existing);
    if (existingDesc.key === sourceDesc.key) {
      if (sourceDesc.subtype === 'api' && sourceDesc.provider === 'custom') {
        return `Rejected: duplicate Custom API with Base URL ${sourceDesc.baseUrl || '(empty)'} is already connected.`;
      }
      return `Rejected: ${sourceDesc.label} is already connected to this LiteLLM node.`;
    }
  }
  return null;
}

function defaultAliases(desc: SourceDescriptor, models: string[]): ModelAlias[] {
  if (desc.provider === 'codex' && models.length > 0) {
    return [{ alias: 'codex', upstream: models[0] }];
  }
  if (desc.provider === 'gemini' && models.length > 0) {
    return [{ alias: 'gemini', upstream: models[0] }];
  }
  if (desc.provider === 'gemini' && desc.subtype === 'api') {
    return [
      { alias: 'gemini', upstream: 'gemini-2.5-pro' },
      { alias: 'gemini-2.5-pro', upstream: 'gemini-2.5-pro' },
      { alias: 'gemini-2.5-flash', upstream: 'gemini-2.5-flash' },
    ];
  }
  if (desc.provider === 'claude') {
    return CLAUDE_CODE_MODEL_ALIASES;
  }
  if (desc.provider === 'anthropic') {
    return [
      { alias: 'claude-api', upstream: 'claude-sonnet-4-6' },
      ...CLAUDE_CODE_MODEL_ALIASES,
    ];
  }
  return [];
}

function sourcePriority(input: Node): string {
  const desc = descriptorFromNode(input);
  const providerRank: Record<string, number> = {
    codex: 10,
    gemini: 20,
    claude: 30,
    openai: 40,
    anthropic: 50,
    deepseek: 60,
    custom: 90,
  };
  const subtypeRank = desc.subtype === 'proxy' ? 0 : 1;
  return `${subtypeRank}:${providerRank[desc.provider] || 80}:${desc.key}:${input.id}`;
}

async function mappingForInputs(
  inputs: Node[],
  baseMapping: Record<string, string> = {},
  baseSources: Record<string, ModelSource> = {},
): Promise<{ mapping: Record<string, string>; sources: Record<string, ModelSource>; fetched: Record<string, string[]> }> {
  const orderedInputs = [...inputs].sort((a, b) => sourcePriority(a).localeCompare(sourcePriority(b)));
  const connectedSourceKeys = new Set(orderedInputs.map(input => descriptorFromNode(input).key));
  const mapping: Record<string, string> = {};
  const sources: Record<string, ModelSource> = {};
  for (const [alias, upstream] of Object.entries(baseMapping)) {
    const owner = baseSources[alias];
    if (!owner || !connectedSourceKeys.has(owner.sourceKey)) continue;
    mapping[alias] = upstream;
    sources[alias] = { ...owner, upstream: String(upstream || owner.upstream || '') };
  }
  const fetched: Record<string, string[]> = {};

  for (const input of orderedInputs) {
    const desc = descriptorFromNode(input);
    const serviceName = serviceNameForInput(input);
    const fetchedModels = serviceName ? await api.fetchProxyModels(serviceName).catch(() => []) : [];
    const models = fetchedModels.length > 0 ? fetchedModels : (serviceName ? (FALLBACK_PROXY_MODELS[serviceName] || []) : []);
    if (serviceName) fetched[desc.label] = fetchedModels;
    for (const item of defaultAliases(desc, models)) {
      addModelAlias(mapping, sources, desc, item.alias, item.upstream, item.effort);
    }
    for (const model of models) {
      const inferred = desc.provider === 'anthropic' ? inferClaudeCodeAlias(model) : null;
      if (inferred) {
        addModelAlias(mapping, sources, desc, inferred.alias, inferred.upstream, inferred.effort);
      } else {
        addModelAlias(mapping, sources, desc, model, model);
      }
    }
  }

  return { mapping, sources, fetched };
}

async function nodesWithFreshMappings(allNodes: Node[], allEdges: Edge[]): Promise<{ nodes: Node[]; refreshed: number }> {
  let refreshed = 0;
  const nodes = await Promise.all(allNodes.map(async n => {
    if (n.type !== 'transform') return n;
    const inputs = connectedInputNodes(n, allNodes, allEdges);
    if (inputs.length === 0) return n;
    const result = await mappingForInputs(inputs, parseMapping(n.data.mapping), n.data.modelSources || {});
    refreshed += 1;
    return {
      ...n,
      data: {
        ...n.data,
        mapping: JSON.stringify(result.mapping, null, 2),
        modelSources: result.sources,
      },
    };
  }));
  return { nodes, refreshed };
}

function graphIssues(allNodes: Node[], allEdges: Edge[]): string[] {
  const issues: string[] = [];
  const localPortsByProvider = new Map<string, Set<number>>();
  const providersByPort = new Map<number, Set<string>>();

  for (const input of allNodes.filter(n => n.type === 'input')) {
    if (!allEdges.some(e => e.source === input.id)) {
      issues.push(`Input [${input.data?.label || input.id}] has no LiteLLM target.`);
    }
    const serviceName = serviceNameForInput(input);
    if (serviceName) {
      const port = Number(input.data?.port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        issues.push(`Input [${input.data?.label || input.id}] has an invalid proxy port.`);
      } else {
        if (!localPortsByProvider.has(serviceName)) localPortsByProvider.set(serviceName, new Set());
        localPortsByProvider.get(serviceName)!.add(port);
        if (!providersByPort.has(port)) providersByPort.set(port, new Set());
        providersByPort.get(port)!.add(serviceName);
      }
    }
  }
  for (const [provider, ports] of localPortsByProvider.entries()) {
    if (ports.size > 1) {
      issues.push(`${PROVIDER_LABELS[provider] || provider} nodes must use one shared port: ${[...ports].join(', ')}.`);
    }
  }
  for (const [port, providers] of providersByPort.entries()) {
    if (providers.size > 1) {
      issues.push(`Local proxy port ${port} is shared by multiple services: ${[...providers].map(p => PROVIDER_LABELS[p] || p).join(', ')}.`);
    }
  }
  for (const transform of allNodes.filter(n => n.type === 'transform')) {
    const inputs = connectedInputNodes(transform, allNodes, allEdges);
    const outputs = connectedOutputNodes(transform, allNodes, allEdges);
    if (inputs.length === 0) issues.push(`LiteLLM node [${transform.data?.label || transform.id}] has no input source.`);
    if (outputs.length === 0) issues.push(`LiteLLM node [${transform.data?.label || transform.id}] has no output node.`);
    for (const input of inputs) {
      const issue = duplicateInputIssue(input, transform, allNodes, allEdges.filter(e => !(e.source === input.id && e.target === transform.id)));
      if (issue) issues.push(issue.replace(/^Rejected: /, 'Duplicate source: '));
    }
  }
  for (const output of allNodes.filter(n => n.type === 'output')) {
    if (!allEdges.some(e => e.target === output.id)) {
      issues.push(`Output [${output.data?.label || output.id}] has no upstream LiteLLM node.`);
    }
  }
  return [...new Set(issues)];
}

function flowsToScheme(flows: any[], serviceStatus: Record<string, any>, config: Record<string, any> = {}): Scheme {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let nodeId = 0;
  const groups = new Map<string, any[]>();
  for (const flow of flows) {
    const middle = flow.layout?.middle || { x: 380, y: 90 + groups.size * 180 };
    const key = `${Math.round(Number(middle.x) || 0)}:${Math.round(Number(middle.y) || 0)}`;
    groups.set(key, [...(groups.get(key) || []), flow]);
  }

  for (const groupFlows of groups.values()) {
    const firstFlow = groupFlows[0] || {};
    const midPos = firstFlow.layout?.middle || { x: 380, y: 90 + nodeId * 120 };
    const midId = `node_${nodeId++}`;
    const merged = mergeFlowModels(groupFlows);

    nodes.push({
      id: midId,
      type: 'transform',
      position: { x: midPos.x, y: midPos.y },
      data: {
        label: 'LiteLLM',
        className: 'LiteLLM',
        mapping: JSON.stringify(merged.mapping, null, 2),
        modelSources: merged.sources,
      },
    });

    for (const flow of groupFlows) {
      const desc = descriptorFromFlow(flow);
      const source = flow.source || {};
      const srcPos = flow.layout?.source || { x: 60, y: 90 + nodeId * 140 };
      const srcId = `node_${nodeId++}`;
      const sourcePort = desc.subtype === 'proxy'
        ? configuredLocalPort(config, desc.provider, serviceStatus[desc.provider]?.port)
        : undefined;
      const healthy = desc.subtype === 'proxy'
        ? Boolean(serviceStatus[desc.provider]?.healthy) && Number(serviceStatus[desc.provider]?.port) === Number(sourcePort)
        : false;
      const protocol = desc.subtype === 'proxy'
        ? (PROVIDER_PROTOCOLS[desc.provider] || 'Custom')
        : (desc.provider === 'anthropic' ? 'Anthropic' : desc.provider === 'gemini' ? 'Gemini' : 'OpenAI');

      nodes.push({
        id: srcId,
        type: 'input',
        position: { x: srcPos.x, y: srcPos.y },
        data: {
          label: desc.label,
          className: desc.label,
          subtype: desc.subtype,
          protocol,
          adapter: desc.adapter,
          port: sourcePort,
          baseUrl: source.base_url || source.baseUrl || desc.baseUrl,
          apiKey: source.api_key || source.apiKey || '',
          status: healthy ? 'online' : 'offline',
          flowId: flow.id,
          provider: desc.provider,
        },
      });
      edges.push({ id: `e_${srcId}_${midId}`, source: srcId, target: midId, animated: true, style: edgeStyle, markerEnd: edgeMarker });
    }

    const outputMap = new Map<string, any>();
    for (const flow of groupFlows) {
      for (const output of flow.outputs || []) {
        const key = `${output.format || 'anthropic'}:${output.port || 4000}:${output.api_key || 'litellm-local-test-key'}`;
        outputMap.set(key, { output, layout: flow.layout || {} });
      }
    }

    let outputIndex = 0;
    for (const { output, layout } of outputMap.values()) {
      const outPos = layout.output || { x: 700, y: midPos.y };
      const outId = `node_${nodeId++}`;
      const fmt = output.format || 'anthropic';
      nodes.push({
        id: outId,
        type: 'output',
        position: { x: outPos.x, y: outPos.y + outputIndex * 150 },
        data: {
          label: FORMAT_LABELS[fmt] || `${fmt} Output`,
          className: FORMAT_LABELS[fmt] || fmt,
          format: fmt,
          port: output.port || 4000,
          protocol: fmt === 'openai' ? 'OpenAI' : fmt === 'gemini' ? 'Gemini' : 'Anthropic',
          apiKey: output.api_key,
        },
      });
      edges.push({ id: `e_${midId}_${outId}`, source: midId, target: outId, animated: true, style: edgeStyle, markerEnd: edgeMarker });
      outputIndex += 1;
    }
  }

  return { id: 'live', name: 'Live Configuration', nodes, edges };
}

function schemeToFlows(nodes: Node[], edges: Edge[], originalFlows: any[]): any[] {
  const flowMap = new Map<string, any>();
  for (const f of originalFlows) flowMap.set(f.id, f);

  const inputNodes = nodes.filter(n => n.type === 'input');
  const flows: any[] = [];

  for (const src of inputNodes) {
    const midEdges = edges.filter(e => e.source === src.id);
    for (const midEdge of midEdges) {
      const mid = nodes.find(n => n.id === midEdge.target && n.type === 'transform');
      if (!mid) continue;

      const outEdges = edges.filter(e => e.source === mid.id);
      const outputs = outEdges
        .map(e => nodes.find(n => n.id === e.target && n.type === 'output'))
        .filter(Boolean)
        .map(out => ({
          format: out!.data.protocol?.toLowerCase() || 'anthropic',
          port: out!.data.port || 4000,
          api_key: out!.data.apiKey || 'litellm-local-test-key',
        }));

      if (outputs.length === 0) continue;

      const provider = src.data.provider || 'custom';
      const flowId = src.data.flowId || `${provider}_${src.id}_${Date.now()}`;
      const original = flowMap.get(flowId);
      const allInputs = connectedInputNodes(mid, nodes, edges);
      const models = modelsForSource(mid, src, allInputs);
      const desc = descriptorFromNode(src);
      const isLocalProxy = desc.subtype === 'proxy' && desc.provider in LOCAL_PROVIDER_PORTS;
      const sourceConfig = isLocalProxy
        ? { kind: 'local', provider: desc.provider }
        : {
            kind: 'external',
            format: formatFromProtocol(src.data.protocol),
            adapter: desc.adapter,
            base_url: src.data.baseUrl || '',
            api_key: src.data.apiKey || '',
          };

      flows.push({
        id: flowId,
        name: original?.name || `${provider} flow`,
        enabled: true,
        source: sourceConfig,
        middle: { kind: 'litellm' },
        outputs,
        models: models.length > 0 ? models : (original?.models || []),
        layout: {
          source: { x: Math.round(src.position.x), y: Math.round(src.position.y) },
          middle: { x: Math.round(mid.position.x), y: Math.round(mid.position.y) },
          output: { x: Math.round(outputs.length > 0 ? (nodes.find(n => n.id === outEdges[0]?.target)?.position.x || 700) : 700), y: Math.round(outputs.length > 0 ? (nodes.find(n => n.id === outEdges[0]?.target)?.position.y || 90) : 90) },
        },
      });
    }
  }
  return flows;
}

function configPortsFromNodes(allNodes: Node[]): Record<string, number> {
  const updates: Record<string, number> = {};
  for (const node of allNodes) {
    if (node.type !== 'input') continue;
    const serviceName = serviceNameForInput(node);
    const configKey = serviceName ? LOCAL_PROVIDER_CONFIG_KEYS[serviceName] : undefined;
    const port = Number(node.data?.port);
    if (configKey && Number.isInteger(port) && port > 0) {
      updates[configKey] = port;
    }
  }
  return updates;
}

function mergeConfigPorts(config: Record<string, any>, allNodes: Node[]): Record<string, any> {
  return { ...config, ...configPortsFromNodes(allNodes) };
}

function healthyForNode(serviceInfo: any, node: Node): boolean {
  const expectedPort = Number(node.data?.port);
  const actualPort = Number(serviceInfo?.port);
  return Boolean(serviceInfo?.healthy) && (!expectedPort || actualPort === expectedPort);
}

function cloneGraph(nodes: Node[], edges: Edge[]): GraphSnapshot {
  return {
    nodes: nodes.map(node => ({
      ...node,
      position: { ...node.position },
      positionAbsolute: node.positionAbsolute ? { ...node.positionAbsolute } : node.positionAbsolute,
      data: { ...node.data },
      style: node.style ? { ...node.style } : node.style,
    })),
    edges: edges.map(edge => ({
      ...edge,
      data: edge.data ? { ...edge.data } : edge.data,
      style: edge.style ? { ...edge.style } : edge.style,
      markerEnd: typeof edge.markerEnd === 'object' && edge.markerEnd ? { ...edge.markerEnd } : edge.markerEnd,
      markerStart: typeof edge.markerStart === 'object' && edge.markerStart ? { ...edge.markerStart } : edge.markerStart,
    })),
  };
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === 'input' || tagName === 'textarea' || tagName === 'select';
}

let nodeIdCounter = 1000;
const getNextNodeId = () => `node_${nodeIdCounter++}`;

// --- PLACEHOLDER_APP_COMPONENT ---

const App = () => {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const mappingRefreshSeqRef = useRef<Record<string, number>>({});
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);
  const graphRef = useRef<GraphSnapshot>({ nodes: [], edges: [] });
  const undoStackRef = useRef<GraphSnapshot[]>([]);
  const clipboardRef = useRef<GraphSnapshot | null>(null);
  const skipHistoryRef = useRef(false);
  const dragHistoryRecordedRef = useRef(false);

  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [logs, setLogs] = useState<Log[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [nodes, setNodes, applyNodesChange] = useNodesState([]);
  const [edges, setEdges, applyEdgesChange] = useEdgesState([]);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [serviceStatus, setServiceStatus] = useState<Record<string, any>>({});
  const [originalFlows, setOriginalFlows] = useState<any[]>([]);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [autoLaunch, setAutoLaunch] = useState(false);
  const [config, setConfig] = useState<Record<string, any>>({});

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  useEffect(() => {
    window.electronAPI?.getAutoLaunch().then(setAutoLaunch).catch(() => {});
    api.fetchConfig().then(setConfig).catch(() => {});
  }, []);

  const addLog = useCallback((message: string, type: Log['type'] = 'info') => {
    const newLog: Log = {
      id: Math.random().toString(36).substr(2, 9),
      timestamp: new Date().toLocaleTimeString([], { hour12: true }),
      message,
      type,
    };
    setLogs(prev => [...prev.slice(-49), newLog]);
  }, []);

  useEffect(() => { document.documentElement.setAttribute('data-theme', theme); }, [theme]);
  useEffect(() => { if (logEndRef.current) logEndRef.current.scrollIntoView({ behavior: 'smooth' }); }, [logs]);
  useEffect(() => {
    nodesRef.current = nodes;
    graphRef.current = { nodes, edges: edgesRef.current };
  }, [nodes]);
  useEffect(() => {
    edgesRef.current = edges;
    graphRef.current = { nodes: nodesRef.current, edges };
  }, [edges]);

  const pushUndoSnapshot = useCallback(() => {
    if (skipHistoryRef.current) return;
    undoStackRef.current = [...undoStackRef.current.slice(-79), cloneGraph(graphRef.current.nodes, graphRef.current.edges)];
  }, []);

  const undoLast = useCallback(() => {
    const previous = undoStackRef.current.pop();
    if (!previous) return;
    skipHistoryRef.current = true;
    setSelectedNodeId(null);
    setNodes(previous.nodes);
    setEdges(previous.edges);
    window.setTimeout(() => { skipHistoryRef.current = false; }, 0);
    addLog('Undo: restored previous canvas state.', 'info');
  }, [setNodes, setEdges, addLog]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const shouldRecord = changes.some(change => {
      if (change.type === 'select' || change.type === 'dimensions') return false;
      if (change.type === 'position') return !dragHistoryRecordedRef.current && change.dragging !== true;
      return true;
    });
    if (shouldRecord) pushUndoSnapshot();
    applyNodesChange(changes);
  }, [applyNodesChange, pushUndoSnapshot]);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    const shouldRecord = changes.some(change => change.type !== 'select');
    if (shouldRecord) pushUndoSnapshot();
    applyEdgesChange(changes);
  }, [applyEdgesChange, pushUndoSnapshot]);

  const loadFromBackend = useCallback(async () => {
    try {
      addLog('Connecting to backend API at 127.0.0.1:39201...', 'info');
      const [flows, sts, cfg] = await Promise.all([api.fetchFlows(), api.fetchStatus(), api.fetchConfig()]);
      const mergedCfg = mergeConfigPorts(cfg, nodesRef.current);
      setServiceStatus(sts);
      setConfig(mergedCfg);
      setOriginalFlows(flows);
      const scheme = flowsToScheme(flows, sts, mergedCfg);

      const providers = new Set(
        scheme.nodes
          .filter(n => n.type === 'input')
          .map(n => serviceNameForInput(n))
          .filter(Boolean) as string[]
      );
      const modelsByProvider: Record<string, string[]> = {};
      await Promise.all([...providers].map(async (p) => {
        try { modelsByProvider[p] = await api.fetchProxyModels(p); } catch { modelsByProvider[p] = []; }
      }));

      const filledNodes = await Promise.all(scheme.nodes.map(async n => {
        if (n.type !== 'transform') return n;
        const inputs = connectedInputNodes(n, scheme.nodes, scheme.edges);
        if (inputs.length === 0) return n;
        const result = await mappingForInputs(inputs, parseMapping(n.data.mapping), n.data.modelSources || {});
        return {
          ...n,
          data: {
            ...n.data,
            mapping: JSON.stringify(result.mapping, null, 2),
            modelSources: result.sources,
          },
        };
      }));

      setNodes(filledNodes);
      setEdges(scheme.edges);
      undoStackRef.current = [];
      setSelectedNodeId(null);
      const healthySvc = Object.values(sts).filter((s: any) => s.healthy).length;
      const totalSvc = Object.keys(sts).length;
      addLog(`Loaded ${flows.length} flow(s), ${filledNodes.length} nodes, ${scheme.edges.length} edges. Services: ${healthySvc}/${totalSvc} healthy.`, 'success');
      for (const [name, info] of Object.entries(sts) as [string, any][]) {
        addLog(`  ${info.healthy ? '●' : '○'} ${name} :${info.port} — ${info.healthy ? 'healthy' : 'unreachable'}${info.pid ? ` (pid ${info.pid})` : ''}`, info.healthy ? 'success' : 'warn');
      }
      for (const [p, models] of Object.entries(modelsByProvider)) {
        if (models.length > 0) addLog(`  Models for ${p}: ${models.join(', ')}`, 'info');
      }
    } catch (err: any) {
      addLog(`Backend connection failed: ${err.message}. Is the Python API server running on port 39201?`, 'error');
    }
  }, [addLog, setNodes, setEdges]);

  useEffect(() => { loadFromBackend(); }, [loadFromBackend]);

  const selectedNodes = useCallback(() => nodesRef.current.filter(node => node.selected), []);

  const deleteNodesById = useCallback((nodeIds: string[], source: 'keyboard' | 'context' = 'keyboard') => {
    const uniqueIds = [...new Set(nodeIds)];
    if (uniqueIds.length === 0) return;
    pushUndoSnapshot();
    const idSet = new Set(uniqueIds);
    setEdges(eds => eds.filter(edge => !idSet.has(edge.source) && !idSet.has(edge.target)));
    setNodes(nds => nds.filter(node => !idSet.has(node.id)));
    if (selectedNodeId && idSet.has(selectedNodeId)) setSelectedNodeId(null);
    addLog(`${uniqueIds.length} node${uniqueIds.length === 1 ? '' : 's'} deleted${source === 'context' ? '.' : ' from selection.'}`, 'info');
    closeContextMenu();
  }, [setNodes, setEdges, selectedNodeId, addLog, closeContextMenu, pushUndoSnapshot]);

  const copySelectedNodes = useCallback(() => {
    const pickedNodes = selectedNodes();
    if (pickedNodes.length === 0) return false;
    const idSet = new Set(pickedNodes.map(node => node.id));
    const pickedEdges = edgesRef.current.filter(edge => idSet.has(edge.source) && idSet.has(edge.target));
    clipboardRef.current = cloneGraph(pickedNodes, pickedEdges);
    addLog(`Copied ${pickedNodes.length} selected node${pickedNodes.length === 1 ? '' : 's'}.`, 'info');
    return true;
  }, [addLog, selectedNodes]);

  const pasteClipboard = useCallback(() => {
    const clipboard = clipboardRef.current;
    if (!clipboard || clipboard.nodes.length === 0) return false;
    pushUndoSnapshot();
    const idMap = new Map<string, string>();
    const nextNodes = clipboard.nodes.map(node => {
      const nextId = getNextNodeId();
      idMap.set(node.id, nextId);
      return {
        ...node,
        id: nextId,
        selected: true,
        position: { x: node.position.x + 40, y: node.position.y + 40 },
        positionAbsolute: node.positionAbsolute
          ? { x: node.positionAbsolute.x + 40, y: node.positionAbsolute.y + 40 }
          : node.positionAbsolute,
        data: { ...node.data, flowId: undefined },
      };
    });
    const nextEdges: Edge[] = [];
    clipboard.edges.forEach((edge, index) => {
      const source = idMap.get(edge.source);
      const target = idMap.get(edge.target);
      if (!source || !target) return;
      nextEdges.push({
        ...edge,
        id: `e_${source}_${target}_${Date.now()}_${index}`,
        source,
        target,
        selected: false,
      });
    });
    const nextIds = new Set(nextNodes.map(node => node.id));
    setNodes(nds => [
      ...nds.map(node => ({ ...node, selected: false })),
      ...nextNodes,
    ]);
    setEdges(eds => [
      ...eds.map(edge => ({ ...edge, selected: false })),
      ...nextEdges,
    ]);
    setSelectedNodeId(nextNodes.length === 1 ? nextNodes[0].id : null);
    addLog(`Pasted ${nextIds.size} node${nextIds.size === 1 ? '' : 's'}.`, 'info');
    return true;
  }, [setNodes, setEdges, addLog, pushUndoSnapshot]);

  const duplicateSelectedOrNode = useCallback((nodeId?: string) => {
    const pickedNodes = selectedNodes();
    if (pickedNodes.length > 1 || (pickedNodes.length === 1 && (!nodeId || pickedNodes[0].id === nodeId))) {
      if (!copySelectedNodes()) return;
      pasteClipboard();
      return;
    }
    if (!nodeId) return;
    const node = nodesRef.current.find(n => n.id === nodeId);
    if (!node) return;
    pushUndoSnapshot();
    const newId = getNextNodeId();
    setNodes(nds => [
      ...nds.map(item => ({ ...item, selected: false })),
      {
        ...node,
        id: newId,
        position: { x: node.position.x + 40, y: node.position.y + 40 },
        positionAbsolute: node.positionAbsolute
          ? { x: node.positionAbsolute.x + 40, y: node.positionAbsolute.y + 40 }
          : node.positionAbsolute,
        selected: true,
        data: { ...node.data, flowId: undefined },
      },
    ]);
    setSelectedNodeId(newId);
    addLog(`Duplicated ${node.data.label}`, 'info');
    closeContextMenu();
  }, [setNodes, selectedNodes, copySelectedNodes, pasteClipboard, pushUndoSnapshot, addLog, closeContextMenu]);

  const recordDragStart = useCallback(() => {
    if (dragHistoryRecordedRef.current) return;
    dragHistoryRecordedRef.current = true;
    pushUndoSnapshot();
  }, [pushUndoSnapshot]);

  const recordDragStop = useCallback(() => {
    dragHistoryRecordedRef.current = false;
  }, []);

  const handleSelectionChange = useCallback(({ nodes: selected }: { nodes: Node[]; edges: Edge[] }) => {
    if (selected.length === 1) {
      setSelectedNodeId(selected[0].id);
    } else if (selected.length !== 1) {
      setSelectedNodeId(null);
    }
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      const modifier = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      if (modifier && key === 'z') {
        event.preventDefault();
        undoLast();
        return;
      }
      if (modifier && key === 'c') {
        if (copySelectedNodes()) event.preventDefault();
        return;
      }
      if (modifier && key === 'v') {
        if (pasteClipboard()) event.preventDefault();
        return;
      }
      if (modifier && key === 'd') {
        const picked = selectedNodes();
        if (picked.length > 0) {
          event.preventDefault();
          duplicateSelectedOrNode();
        }
        return;
      }
      if (event.key === 'Backspace' || event.key === 'Delete') {
        const picked = selectedNodes();
        if (picked.length === 0) return;
        event.preventDefault();
        deleteNodesById(picked.map(node => node.id), 'keyboard');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [undoLast, copySelectedNodes, pasteClipboard, selectedNodes, duplicateSelectedOrNode, deleteNodesById]);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const sts = await api.fetchStatus();
        setServiceStatus(sts);
        setNodes(prev => prev.map(n => {
          if (n.type !== 'input') return n;
      const serviceName = serviceNameForInput(n);
      if (!serviceName || !sts[serviceName]) return n;
      const healthy = healthyForNode(sts[serviceName], n);
      return { ...n, data: { ...n.data, status: healthy ? 'online' : 'offline' } };
        }));
      } catch {}
    }, 8000);
    return () => clearInterval(interval);
  }, [setNodes]);

  const triggerSave = useCallback(async () => {
    setIsSaving(true);
    try {
      const { nodes: freshNodes, refreshed } = await nodesWithFreshMappings(nodes, edges);
      if (refreshed > 0) {
        setNodes(freshNodes);
        addLog(`Model mapping refreshed before save for ${refreshed} LiteLLM node(s).`, 'info');
      }
      const issues = graphIssues(freshNodes, edges);
      if (issues.length > 0) {
        for (const issue of issues) addLog(`Save blocked: ${issue}`, 'error');
        throw new Error(`Graph has ${issues.length} structural issue(s)`);
      }
      const flows = schemeToFlows(freshNodes, edges, originalFlows);
      const portUpdates = configPortsFromNodes(freshNodes);
      addLog(`Saving ${flows.length} flow(s) with ${freshNodes.length} nodes, ${edges.length} edges...`, 'info');
      if (Object.keys(portUpdates).length > 0) {
        await api.updateConfig(portUpdates);
        setConfig(prev => ({ ...prev, ...portUpdates }));
        addLog(`Updated local proxy port config: ${Object.entries(portUpdates).map(([key, value]) => `${key}=${value}`).join(', ')}.`, 'info');
      }
      await api.saveFlows(flows);
      setOriginalFlows(flows);
      addLog(`Configuration saved successfully. ${flows.map(f => f.id).join(', ')}`, 'success');
      return true;
    } catch (err: any) {
      addLog(`Save failed: ${err.message}`, 'error');
      return false;
    } finally {
      setIsSaving(false);
    }
  }, [nodes, edges, originalFlows, addLog]);

  const validateArchitecture = useCallback(async () => {
    const issues = graphIssues(nodes, edges);
    addLog(`Structural validation: ${nodes.length} node(s), ${edges.length} edge(s).`, 'info');
    if (issues.length > 0) {
      for (const issue of issues) addLog(`Validation Error: ${issue}`, 'error');
      addLog(`Validation failed before runtime checks: ${issues.length} issue(s).`, 'error');
      return;
    }

    const saved = await triggerSave();
    if (!saved) {
      addLog('Runtime validation skipped because the latest graph could not be saved.', 'error');
      return;
    }
    addLog('Runtime validation: restarting services so LiteLLM reloads the saved flow config...', 'info');
    try {
      await api.restartServices();
      const freshStatus = await api.fetchStatus();
      setServiceStatus(freshStatus);
      setNodes(prev => prev.map(n => {
        if (n.type !== 'input') return n;
        const serviceName = serviceNameForInput(n);
        if (!serviceName || !freshStatus[serviceName]) return n;
        return { ...n, data: { ...n.data, status: healthyForNode(freshStatus[serviceName], n) ? 'online' : 'offline' } };
      }));
      addLog('Runtime validation: checking service health and LiteLLM model routes...', 'info');
      const result = await api.validateFlows();
      for (const check of result.checks || []) {
        const message = `${check.ok ? 'PASS' : 'FAIL'} ${check.name}${check.port ? ` :${check.port}` : ''} — ${check.detail}`;
        addLog(message, check.ok ? 'success' : 'error');
        if (check.kind === 'output' && check.expected_models?.length) {
          addLog(`  expected models: ${check.expected_models.join(', ')}`, 'info');
        }
      }
      addLog(result.ok ? 'Validation successful: configured services and model routes are reachable.' : 'Validation failed: see failed checks above.', result.ok ? 'success' : 'error');
    } catch (err: any) {
      addLog(`Runtime validation failed: ${err.message}`, 'error');
    }
  }, [triggerSave, nodes, edges, addLog]);

  const onConnect = useCallback((params: Connection) => {
    const srcNode = nodes.find(n => n.id === params.source);
    const tgtNode = nodes.find(n => n.id === params.target);

    if (srcNode?.type === 'input' && tgtNode?.type === 'transform') {
      const issue = duplicateInputIssue(srcNode, tgtNode, nodes, edges);
      if (issue) {
        addLog(issue, 'error');
        return;
      }
    }

    pushUndoSnapshot();
    setEdges(eds => {
      const newEdges = addEdge({ ...params, animated: true, style: edgeStyle, markerEnd: edgeMarker }, eds);

      if (srcNode?.type === 'input' && tgtNode?.type === 'transform') {
        const allInputNodes: Node[] = newEdges
            .filter(e => e.target === tgtNode.id)
            .map(e => nodes.find(n => n.id === e.source && n.type === 'input'))
            .filter((node): node is Node => Boolean(node));
        const requestId = (mappingRefreshSeqRef.current[tgtNode.id] || 0) + 1;
        mappingRefreshSeqRef.current[tgtNode.id] = requestId;

        mappingForInputs(allInputNodes, parseMapping(tgtNode.data.mapping), tgtNode.data.modelSources || {})
          .then(result => {
            if (mappingRefreshSeqRef.current[tgtNode.id] !== requestId) return;
            const mapping = JSON.stringify(result.mapping, null, 2);
            setNodes(nds => nds.map(n => n.id === tgtNode.id ? { ...n, data: { ...n.data, mapping, modelSources: result.sources } } : n));
            const sourceLabels = allInputNodes.map(n => descriptorFromNode(n).label).join(', ');
            addLog(`Model mapping updated: ${Object.keys(result.mapping).length} alias(es) from ${sourceLabels}.`, 'success');
            for (const [label, models] of Object.entries(result.fetched)) {
              addLog(`  ${label}: ${models.length ? models.join(', ') : 'no models returned'}`, models.length ? 'info' : 'warn');
            }
          })
          .catch(err => addLog(`Model mapping update failed: ${err.message}`, 'error'));
      }

      return newEdges;
    });

    addLog(`Edge connected: ${srcNode?.data.label || params.source} → ${tgtNode?.data.label || params.target}`, 'info');
  }, [setEdges, addLog, nodes, edges, setNodes, pushUndoSnapshot]);

  const refreshTransformMapping = useCallback((transformId: string, reason: 'select' | 'manual' = 'select') => {
    const transform = nodes.find(n => n.id === transformId && n.type === 'transform');
    if (!transform) return;
    const inputs = connectedInputNodes(transform, nodes, edges);
    if (inputs.length === 0) return;
    const requestId = (mappingRefreshSeqRef.current[transformId] || 0) + 1;
    mappingRefreshSeqRef.current[transformId] = requestId;

    mappingForInputs(inputs, parseMapping(transform.data.mapping), transform.data.modelSources || {})
      .then(result => {
        if (mappingRefreshSeqRef.current[transformId] !== requestId) return;
        setNodes(nds => nds.map(n => n.id === transformId ? {
            ...n,
            data: {
              ...n.data,
              mapping: JSON.stringify(result.mapping, null, 2),
              modelSources: result.sources,
            },
          } : n));
        const sourceLabels = inputs.map(n => descriptorFromNode(n).label).join(', ');
        addLog(`Model mapping refreshed (${reason}): ${Object.keys(result.mapping).length} alias(es) from ${sourceLabels}.`, 'success');
        for (const [label, models] of Object.entries(result.fetched)) {
          addLog(`  ${label}: ${models.length ? models.join(', ') : 'no models returned'}`, models.length ? 'info' : 'warn');
        }
      })
      .catch(err => addLog(`Model mapping refresh failed: ${err.message}`, 'error'));
  }, [nodes, edges, setNodes, addLog]);

  const onDragOver = useCallback((event: React.DragEvent) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; }, []);

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const bounds = reactFlowWrapper.current?.getBoundingClientRect();
    const nodeData = JSON.parse(event.dataTransfer.getData('application/reactflow'));
    if (!nodeData || !bounds) return;
    const position = reactFlowInstance.project({ x: event.clientX - bounds.left, y: event.clientY - bounds.top });

    const serviceName = nodeData.type === 'input' && nodeData.subtype === 'proxy' ? nodeData.provider : null;
    const serviceInfo = serviceName ? serviceStatus[serviceName] : null;
    const newData = {
      ...nodeData,
      status: serviceInfo?.healthy && Number(serviceInfo?.port) === Number(configuredLocalPort(config, nodeData.provider, serviceInfo?.port)) ? 'online' : 'offline',
      port: nodeData.type === 'input' && nodeData.subtype === 'proxy'
        ? configuredLocalPort(config, nodeData.provider, serviceInfo?.port) || nodeData.port || 39121
        : nodeData.port,
    };

    pushUndoSnapshot();
    setNodes(nds => nds.concat({ id: getNextNodeId(), type: nodeData.type, position, data: newData }));
    addLog(`Deployed ${nodeData.type} node "${nodeData.label}" at (${Math.round(position.x)}, ${Math.round(position.y)})`, 'info');
  }, [reactFlowInstance, setNodes, addLog, serviceStatus, config, pushUndoSnapshot]);

  const testNodeAvailability = async (nodeId: string) => {
    const node = nodes.find(n => n.id === nodeId);
    const serviceName = node ? serviceNameForInput(node) : null;
    const desc = node ? descriptorFromNode(node) : null;
    addLog(`Testing connectivity for ${node?.data.label}${serviceName ? ` (service: ${serviceName})` : ''}...`, 'info');
    try {
      if (node && desc?.subtype === 'api') {
        const result = await api.testExternalApi({
          provider: desc.provider,
          protocol: node.data.protocol,
          baseUrl: node.data.baseUrl,
          apiKey: node.data.apiKey,
        });
        setNodes(nds => nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, status: result.ok ? 'online' : 'offline' } } : n));
        if (result.ok) {
          const models = result.models?.length ? `, ${result.models.length} model(s)` : '';
          addLog(`${node.data.label} is ONLINE — ${result.detail || 'external API reachable'}${models}`, 'success');
        } else {
          const lastAttempt = result.attempts?.slice(-1)[0];
          addLog(`${node.data.label} is OFFLINE — ${result.detail || lastAttempt?.detail || 'external API check failed'}`, 'error');
        }
        return;
      }

      const sts = await api.fetchStatus();
      setServiceStatus(sts);
      const svcInfo = serviceName ? sts[serviceName] : null;
      const isOnline = node ? healthyForNode(svcInfo, node) : false;
      setNodes(nds => nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, status: isOnline ? 'online' : 'offline' } } : n));
      if (isOnline) {
        addLog(`${node?.data.label} is ONLINE — port ${svcInfo?.port}, pid ${svcInfo?.pid || 'external/launchd'}`, 'success');
      } else {
        addLog(`${node?.data.label} is OFFLINE — health check at ${svcInfo?.health_url || 'unknown'} failed`, 'error');
      }
    } catch (err: any) {
      addLog(`Test failed for ${node?.data.label}: ${err.message}`, 'error');
    }
  };

  const refreshRuntimeStatus = useCallback(async () => {
    const sts = await api.fetchStatus();
    setServiceStatus(sts);
    setNodes(prev => prev.map(n => {
      if (n.type !== 'input') return n;
      const serviceName = serviceNameForInput(n);
      if (!serviceName || !sts[serviceName]) return n;
      return { ...n, data: { ...n.data, status: healthyForNode(sts[serviceName], n) ? 'online' : 'offline' } };
    }));
    return sts;
  }, [setNodes]);

  const runServiceAction = useCallback(async (label: string, action: () => Promise<any>) => {
    addLog(`${label}: request sent to backend...`, 'info');
    try {
      const response = await action();
      for (const item of response.result || []) {
        const ok = item.healthy ?? item.started ?? item.stopped;
        const detail = item.reason || item.error || item.via || item.log || '';
        addLog(`${label}: ${item.name} ${ok ? 'ok' : 'not ready'}${detail ? ` — ${detail}` : ''}`, ok ? 'success' : 'warn');
      }
      await refreshRuntimeStatus();
    } catch (err: any) {
      addLog(`${label} failed: ${err.message}`, 'error');
    }
  }, [addLog, refreshRuntimeStatus]);

  const updateNodeData = useCallback((nodeId: string, newData: any) => {
    const serviceName = serviceNameForData(newData);
    const nextPort = Number(newData?.port);
    pushUndoSnapshot();
    setNodes(nds => nds.map(n => {
      if (n.id === nodeId) return { ...n, data: newData };
      if (serviceName && serviceNameForInput(n) === serviceName && Number.isInteger(nextPort) && nextPort > 0) {
        return { ...n, data: { ...n.data, port: nextPort } };
      }
      return n;
    }));
  }, [setNodes, pushUndoSnapshot]);

  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: Node) => {
    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, nodeId: node.id });
    setSelectedNodeId(node.id);
  }, []);

  const duplicateNode = useCallback((nodeId: string) => {
    duplicateSelectedOrNode(nodeId);
  }, [duplicateSelectedOrNode]);

  const deleteNode = useCallback((nodeId: string) => {
    const picked = selectedNodes();
    const ids = picked.some(node => node.id === nodeId) ? picked.map(node => node.id) : [nodeId];
    deleteNodesById(ids, 'context');
  }, [deleteNodesById, selectedNodes]);

  const renameNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    closeContextMenu();
  }, [closeContextMenu]);

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    if (node.type === 'transform') refreshTransformMapping(node.id);
  }, [refreshTransformMapping]);

  const currentSelectedNode = nodes.find(n => n.id === selectedNodeId) || null;

  useEffect(() => {
    if (currentSelectedNode?.type === 'transform') {
      refreshTransformMapping(currentSelectedNode.id);
    }
  }, [currentSelectedNode?.id, edges.length]);

  // --- PLACEHOLDER_RETURN ---

  return (
    <div className="flex flex-col h-screen w-screen bg-[var(--bg-main)] text-[var(--text-primary)] overflow-hidden font-sans transition-colors duration-300">
      {/* Header — draggable title bar */}
      <header className="h-14 border-b border-[var(--border-main)] flex items-center justify-between px-6 bg-[var(--bg-sidebar)] z-50 shrink-0 shadow-2xl drag-region">
        <div className="flex items-center gap-6 no-drag">
          <div className="flex items-center gap-3 group pl-16">
            <div className="w-9 h-9 bg-[var(--accent)] rounded-xl flex items-center justify-center shadow-lg transition-transform group-hover:scale-105">
              <Zap size={20} className="text-white fill-current" />
            </div>
            <h1 className="font-black text-xl tracking-tighter uppercase italic select-none">Proxy<span className="text-[var(--accent)]">Everything</span></h1>
          </div>
          <div className="h-6 w-px bg-[var(--border-main)]" />
          {/* Service controls */}
          <div className="flex items-center gap-2">
            <button onClick={() => runServiceAction('Start services', api.startServices)} className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold text-[var(--text-secondary)] hover:text-green-500 bg-[var(--text-primary)]/[0.05] hover:bg-green-500/10 rounded-lg border border-[var(--border-main)] transition-all"><Play size={12} /> Start</button>
            <button onClick={() => runServiceAction('Restart services', api.restartServices)} className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold text-[var(--text-secondary)] hover:text-blue-500 bg-[var(--text-primary)]/[0.05] hover:bg-blue-500/10 rounded-lg border border-[var(--border-main)] transition-all"><RotateCcw size={12} /> Restart</button>
            <button onClick={() => runServiceAction('Stop services', api.stopServices)} className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold text-[var(--text-secondary)] hover:text-red-500 bg-[var(--text-primary)]/[0.05] hover:bg-red-500/10 rounded-lg border border-[var(--border-main)] transition-all"><Square size={12} /> Stop</button>
          </div>
        </div>

        <div className="flex items-center gap-4 no-drag">
          {window.electronAPI && (
            <button
              onClick={async () => {
                const next = !autoLaunch;
                const result = await window.electronAPI!.setAutoLaunch(next);
                setAutoLaunch(result);
                addLog(`Launch at login: ${result ? 'enabled' : 'disabled'}`, result ? 'success' : 'info');
              }}
              className={clsx(
                "flex items-center gap-2 px-3 py-1.5 text-[10px] font-bold rounded-lg border transition-all",
                autoLaunch
                  ? "text-green-500 bg-green-500/10 border-green-500/20"
                  : "text-[var(--text-secondary)] bg-[var(--text-primary)]/[0.05] border-[var(--border-main)] hover:text-[var(--text-primary)]"
              )}
              title="Launch at login"
            >
              <div className={clsx("w-7 h-4 rounded-full relative transition-colors", autoLaunch ? "bg-green-500" : "bg-[var(--text-secondary)]/30")}>
                <div className={clsx("absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all", autoLaunch ? "left-3.5" : "left-0.5")} />
              </div>
              Auto Start
            </button>
          )}
          <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} className="p-2 hover:bg-[var(--text-primary)]/[0.05] rounded-xl transition-all text-[var(--text-secondary)] hover:text-[var(--text-primary)]" title="Switch Theme">
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <div className="h-6 w-px bg-[var(--border-main)]" />
          <button onClick={loadFromBackend} className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all active:scale-95">
            <RotateCcw size={14} /> Reload
          </button>
          <button onClick={triggerSave} disabled={isSaving} className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all active:scale-95 disabled:opacity-50">
            {isSaving ? <Loader2 size={14} className="animate-spin text-[var(--accent)]" /> : <Save size={14} />}
            {isSaving ? 'Saving...' : 'Save Config'}
          </button>
          <button onClick={validateArchitecture} className="flex items-center gap-2 px-6 py-2 text-xs font-black text-white bg-[var(--accent)] hover:opacity-90 rounded-xl shadow-lg transition-all active:scale-95">
            <CheckCircle2 size={16} /> VALIDATE
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden min-h-0">
        <Sidebar />

        <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg-main)]">
          <div className="flex-1 relative" ref={reactFlowWrapper}>
            <ReactFlow
              nodes={nodes} edges={edges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onInit={setReactFlowInstance}
              onDrop={onDrop} onDragOver={onDragOver}
              onNodeClick={handleNodeClick}
              onNodeContextMenu={onNodeContextMenu}
              onNodeDragStart={recordDragStart}
              onNodeDragStop={recordDragStop}
              onSelectionDragStart={recordDragStart}
              onSelectionDragStop={recordDragStop}
              onSelectionChange={handleSelectionChange}
              onPaneClick={() => { setSelectedNodeId(null); closeContextMenu(); }}
              nodeTypes={nodeTypes} fitView snapToGrid snapGrid={[20, 20]}
              selectionOnDrag
              panOnDrag={[1]}
              panOnScroll
              deleteKeyCode={null}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="var(--border-main)" gap={20} size={1} />
              <Controls className="!bg-[var(--bg-card)] !border-[var(--border-main)] !fill-[var(--text-primary)] !shadow-none !rounded-xl !overflow-hidden" />
            </ReactFlow>
          </div>

          {/* Runtime Logs Panel */}
          <div className="h-60 bg-[var(--bg-sidebar)] border-t border-[var(--border-main)] flex flex-col shrink-0 shadow-2xl">
            <div className="px-5 py-3 border-b border-[var(--border-main)] flex items-center justify-between bg-[var(--text-primary)]/[0.02]">
              <div className="flex items-center gap-2.5">
                <Terminal size={14} className="text-[var(--accent)]" />
                <h3 className="text-[11px] font-black uppercase tracking-[0.2em]">Runtime Terminal</h3>
              </div>
              <button onClick={() => setLogs([])} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"><Trash2 size={14} /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-2 font-mono text-[11px] scrollbar-thin">
              {logs.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center text-[var(--text-secondary)] gap-3">
                  <ShieldAlert size={20} className="animate-pulse" />
                  <span className="italic tracking-wider uppercase font-bold text-[9px]">Kernel Standby...</span>
                </div>
              )}
              {logs.map(log => (
                <div key={log.id} className="flex gap-4 group animate-in fade-in slide-in-from-left-2 duration-300">
                  <span className="text-[var(--text-secondary)] shrink-0 select-none">[{log.timestamp}]</span>
                  <span className={clsx("font-medium leading-relaxed", log.type === 'success' ? 'text-green-500' : log.type === 'error' ? 'text-red-500 font-bold' : log.type === 'warn' ? 'text-yellow-500' : 'text-blue-500')}>{log.message}</span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>
        </div>

        {currentSelectedNode ? (
          <Inspector
            selectedNode={currentSelectedNode}
            onUpdateNode={updateNodeData}
            onClose={() => setSelectedNodeId(null)}
            onTestNode={testNodeAvailability}
            allNodes={nodes}
            allEdges={edges}
            onRefreshMapping={(nodeId) => refreshTransformMapping(nodeId, 'manual')}
          />
        ) : (
          <div className="w-80 bg-[var(--bg-sidebar)] border-l border-[var(--border-main)] flex flex-col h-full shrink-0 overflow-y-auto scrollbar-thin">
            <div className="p-5 border-b border-[var(--border-main)] bg-[var(--text-primary)]/[0.03]">
              <div className="flex items-center gap-2">
                <Settings size={16} className="text-[var(--accent)]" />
                <h2 className="text-sm font-bold text-[var(--text-primary)]">Settings</h2>
              </div>
            </div>
            <div className="p-5 space-y-6">
              {/* Service Status */}
              <section>
                <h3 className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-widest mb-3">Services</h3>
                <div className="space-y-2">
                  {Object.entries(serviceStatus).map(([name, info]: [string, any]) => (
                    <div key={name} className="flex items-center gap-2 px-3 py-2 bg-[var(--text-primary)]/[0.03] rounded-lg border border-[var(--border-main)]">
                      <div className={clsx("w-2 h-2 rounded-full", info.healthy ? "bg-green-500" : "bg-red-500")} />
                      <span className="text-[11px] text-[var(--text-primary)] font-bold">{name}</span>
          <span className="text-[10px] text-[var(--text-secondary)] ml-auto font-mono">:{info.port}</span>
          {info.log && <span className="text-[9px] text-[var(--text-secondary)] truncate max-w-[110px]" title={info.log}>{info.healthy ? 'ready' : 'check log'}</span>}
        </div>
      ))}
                </div>
              </section>
              {/* API Keys */}
              <section>
                <h3 className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-widest mb-2">API Keys</h3>
                <p className="text-[9px] text-[var(--text-secondary)] italic mb-3">Configure API keys on each Input / Output node directly.</p>
              </section>
            </div>
          </div>
        )}
      </div>

      {/* Node Context Menu */}
      {contextMenu && (
        <>
          <div className="fixed inset-0 z-[999]" onClick={closeContextMenu} onContextMenu={(e) => { e.preventDefault(); closeContextMenu(); }} />
          <div
            className="context-menu fixed z-[1000] bg-[var(--bg-card)] border border-[var(--border-main)] rounded-xl shadow-2xl py-1.5 min-w-[200px] backdrop-blur-xl"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button onClick={() => renameNode(contextMenu.nodeId)} className="w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-[var(--text-primary)] hover:bg-[var(--accent-soft)] transition-colors">
              <Pencil size={14} className="text-[var(--text-secondary)]" /> Edit Node
            </button>
            <button onClick={() => duplicateNode(contextMenu.nodeId)} className="w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-[var(--text-primary)] hover:bg-[var(--accent-soft)] transition-colors">
              <Copy size={14} className="text-[var(--text-secondary)]" />
              <span className="flex-1 text-left">Duplicate</span>
              <span className="text-[11px] text-[var(--text-secondary)]">⌘ D</span>
            </button>
            <div className="my-1.5 border-t border-[var(--border-main)]" />
            <button onClick={() => deleteNode(contextMenu.nodeId)} className="w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-red-400 hover:bg-red-500/10 transition-colors">
              <Trash size={14} />
              <span className="flex-1 text-left">Delete</span>
              <span className="text-[11px] text-red-400/60">Del</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default () => (
  <ReactFlowProvider>
    <App />
  </ReactFlowProvider>
);

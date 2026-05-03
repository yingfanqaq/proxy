const API_BASE = 'http://127.0.0.1:39201';

export async function fetchStatus(): Promise<Record<string, { healthy: boolean; port: number; pid: number | null; health_url?: string; log?: string }>> {
  const res = await fetch(`${API_BASE}/api/status`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function fetchFlows(): Promise<any[]> {
  const res = await fetch(`${API_BASE}/api/flows`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function saveFlows(flows: any[]): Promise<void> {
  const res = await fetch(`${API_BASE}/api/flows`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flows),
  });
  if (!res.ok) throw new Error(`status ${res.status}`);
}

export async function saveAndRestart(flows: any[]): Promise<void> {
  const res = await fetch(`${API_BASE}/api/flows/save-and-restart`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flows),
  });
  if (!res.ok) throw new Error(`status ${res.status}`);
}

export async function startServices(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/services/start`, { method: 'POST' });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function stopServices(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/services/stop`, { method: 'POST' });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function restartServices(): Promise<any> {
  const res = await fetch(`${API_BASE}/api/services/restart`, { method: 'POST' });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function validateFlows(): Promise<{ ok: boolean; checks: any[]; error?: string }> {
  const res = await fetch(`${API_BASE}/api/flows/validate`, { method: 'POST' });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function fetchConfig(): Promise<Record<string, any>> {
  const res = await fetch(`${API_BASE}/api/config`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

export async function updateConfig(data: Record<string, any>): Promise<void> {
  const res = await fetch(`${API_BASE}/api/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`status ${res.status}`);
}

export async function fetchProxyModels(provider: string): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/proxy-models/${provider}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.models || [];
}

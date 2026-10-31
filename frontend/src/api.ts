import type { CopilotResponse, DocumentSummary, ResearchTask, Run, Workspace } from './types';

const API = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const getWorkspace = () => request<Workspace>('/workspace');
export const getRun = (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`);
export const runDemo = () => request<Run>('/runs/demo', { method: 'POST' });
export async function createRun(args: {
  fundId: string;
  report?: File | null;
  priorReport?: File | null;
  benchmark?: File | null;
  extraText?: string;
  documentIds?: string[];
  priorDocumentIds?: string[];
  useAi?: boolean;
}): Promise<Run> {
  const body = new FormData();
  body.append('fund_id', args.fundId);
  if (args.report) body.append('report', args.report);
  if (args.priorReport) body.append('prior_report', args.priorReport);
  if (args.benchmark) body.append('benchmark', args.benchmark);
  body.append('extra_text', args.extraText || '');
  body.append('document_ids', JSON.stringify(args.documentIds || []));
  body.append('prior_document_ids', JSON.stringify(args.priorDocumentIds || []));
  body.append('use_ai', args.useAi ? 'true' : 'false');
  return request<Run>('/runs', { method: 'POST', body });
}
export const askCopilot = (question: string, fundId?: string) => request<CopilotResponse>('/copilot', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({question, fund_id:fundId}) });
export const updateTask = (id: string, status: ResearchTask['status'], resolutionNote?: string) => request<ResearchTask>(`/tasks/${encodeURIComponent(id)}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,resolution_note:resolutionNote})});
export const searchDocuments = (q: string, fundId?: string) => request<{query:string;results:{document_id:string;source:string;fund_id:string;location:string;text:string;score:number}[];notice?:string}>(`/search?q=${encodeURIComponent(q)}${fundId ? `&fund_id=${encodeURIComponent(fundId)}` : ''}`);
export async function uploadDocument(file: File, fundId: string, period: string): Promise<DocumentSummary> {
  const body = new FormData();
  body.append('file', file);
  body.append('fund_id', fundId);
  body.append('period', period);
  return request<DocumentSummary>('/documents', { method: 'POST', body });
}
export const getDocument = (id: string) => request<DocumentSummary>(`/documents/${encodeURIComponent(id)}`);
export async function importData(kind: 'funds' | 'nav' | 'holdings', file: File, mapping: Record<string, string>, fundId?: string): Promise<unknown> {
  const body = new FormData();
  body.append('file', file);
  body.append('mapping', JSON.stringify(mapping));
  if (fundId) body.append('fund_id', fundId);
  return request<unknown>(`/imports/${kind}`, { method: 'POST', body });
}
export async function downloadReport(id: string, format: 'markdown' | 'json', fundId: string) {
  const response = await fetch(`${API}/reports/${encodeURIComponent(id)}?format=${format}`);
  if (!response.ok) throw new Error(`导出失败（HTTP ${response.status}）`);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = `${fundId}_尽调${format === 'markdown' ? '.md' : '.json'}`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

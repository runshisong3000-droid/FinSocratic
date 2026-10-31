import type { Fund, Holding } from './types';

export const pct = (v?: number | null, digits = 2) => v === undefined || v === null || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(digits)}%`;
export const num = (v?: number | null, digits = 0) => v === undefined || v === null || !Number.isFinite(v) ? '—' : v.toLocaleString('zh-CN', {maximumFractionDigits:digits});
export const dateText = (v?: string) => v ? new Date(v).toLocaleDateString('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit'}) : '—';
export const timeText = (v?: string) => v ? new Date(v).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
export const colors = ['#079b83', '#3e67ce', '#d6a347', '#8b72c5', '#738b9b', '#cb6f81'];
export const statusColor: Record<string,string> = {supported_within_scope:'teal', contradicted:'red', inconclusive:'orange', unverifiable:'gray'};
export const shortStatus: Record<string,string> = {supported_within_scope:'样本相符', contradicted:'数据矛盾', inconclusive:'证据不足', unverifiable:'待核验'};
export function latestHoldings(fund?: Fund): Holding[] {
  const all = fund?.holdings || [];
  const latest = all.reduce((max,h)=>h.as_of > max ? h.as_of : max, '');
  return all.filter(h=>h.as_of===latest);
}
export function navChart(funds: Fund[]) {
  const rows: Record<string, any> = {};
  funds.forEach(f => { const first = f.nav?.[0]?.nav || 1; (f.nav || []).forEach(p=>{ rows[p.date] ||= {date:p.date}; rows[p.date][f.name] = +(p.nav / first * 100).toFixed(2); }); });
  return Object.entries(rows).sort(([a],[b])=>a.localeCompare(b)).map(([,v])=>v);
}
export function allocationChart(fund?: Fund) {
  const rows: Record<string, any> = {};
  (fund?.holdings_history || []).forEach(h=>{ rows[h.as_of] ||= {date:h.as_of}; rows[h.as_of][h.asset] = (rows[h.as_of][h.asset] || 0)+h.weight_pct; });
  return Object.entries(rows).sort(([a],[b])=>a.localeCompare(b)).map(([,v])=>v);
}
export function allocationChanges(fund?: Fund) {
  const rows=allocationChart(fund); if(rows.length<2)return [];
  const before=rows[rows.length-2],after=rows[rows.length-1];
  return [...new Set([...Object.keys(before),...Object.keys(after)])].filter(k=>k!=='date').map(asset=>({asset,before:before[asset]||0,after:after[asset]||0,change:(after[asset]||0)-(before[asset]||0)})).sort((a,b)=>Math.abs(b.change)-Math.abs(a.change));
}

import { useState } from 'react';
import { Alert, Badge, Button, Group, Stack, Switch, Table, Text, TextInput, Anchor, SimpleGrid } from '@mantine/core';
import { IconSearch, IconDownload, IconWorld, IconExternalLink } from '@tabler/icons-react';
import { Panel } from './components';
import type { PageProps } from './pages';

type Candidate = { code: string; name: string; type: string };
async function api(path: string, body?: unknown) {
  const response = await fetch(`/api/market/${path}`, body ? { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) } : undefined);
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '数据请求失败');
  return result;
}

export function MarketData(p: PageProps) {
  const [query, setQuery] = useState('');
  const [fof, setFof] = useState(true);
  const [results, setResults] = useState<Candidate[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<any>(null);
  async function search() {
    setBusy('search'); setError('');
    try { const data = await api(`search?q=${encodeURIComponent(query)}&fof_only=${fof}`); setResults(data.results); setTotal(data.total); }
    catch (e: any) { setError(e.message); } finally { setBusy(''); }
  }
  async function importFund(code: string) {
    setBusy(code); setError('');
    try { const data = await api('import', { code }); setReceipt(data); await p.refresh(); p.setFund(data.fund_id); p.notify(`已接入 ${data.imported} 个日频观测`); }
    catch (e: any) { setError(e.message); } finally { setBusy(''); }
  }
  async function importDisclosure() {
    setBusy('disclosure'); setError('');
    try { const data = await api('disclosure', {code:'005215'}); await p.refresh(); p.notify(`原始季报已入库，${data.chunks_count} 页可检索`); p.openDoc(data.document_id); }
    catch (e: any) {setError(e.message);} finally {setBusy('');}
  }
  return <Panel title="公开基金研究接入" subtitle="搜索真实 FOF，获取历史日频数据；保存来源、抓取时间与内容指纹" className="section-gap">
    <Stack>
      <Group align="end"><TextInput style={{flex:1}} label="基金名称 / 六位代码" placeholder="例如：南方全天候，或 005215" value={query} onChange={e=>setQuery(e.currentTarget.value)} onKeyDown={e=>e.key==='Enter'&&!busy&&search()} leftSection={<IconSearch size={16}/>}/><Button onClick={search} loading={busy==='search'} disabled={!!busy&&busy!=='search'} leftSection={<IconWorld size={16}/>}>搜索公开目录</Button></Group>
      <Group justify="space-between"><Switch checked={fof} onChange={e=>setFof(e.currentTarget.checked)} label="仅看 FOF"/><Text size="xs" c="dimmed">东方财富 / 天天基金 · 本地缓存 · 按需联网</Text></Group>
      {error&&<Alert color="red">{error}</Alert>}
      <Alert color="gray" title="原始披露案例 · 南方全天候策略 FOF">
        <Text size="sm">管理人官网 2025 年第二季度报告：产品条款、经理说明、业绩和投资组合。作为历史研究案例，非最新披露。</Text>
        <Group mt="sm"><Button size="xs" variant="light" disabled={!!busy&&busy!=='disclosure'||!p.workspace.funds.some(f=>f.fund_id==='CN-005215')} loading={busy==='disclosure'} onClick={importDisclosure}>接入原始季报</Button><Anchor size="xs" href="https://www.nffund.com/main/files/2025/07/18/448922561903.pdf" target="_blank" rel="noreferrer">管理人原文</Anchor><Text size="xs" c="dimmed">先搜索并接入 005215</Text></Group>
      </Alert>
      {total!==null&&<Text size="sm" c="dimmed">匹配 {total} 只，展示前 {results.length} 只；排序不代表推荐。</Text>}
      {!!results.length&&<Table.ScrollContainer minWidth={540}><Table highlightOnHover><Table.Thead><Table.Tr><Table.Th>代码</Table.Th><Table.Th>基金</Table.Th><Table.Th>类别</Table.Th><Table.Th/></Table.Tr></Table.Thead><Table.Tbody>{results.map(f=><Table.Tr key={f.code}><Table.Td>{f.code}</Table.Td><Table.Td>{f.name}</Table.Td><Table.Td><Badge variant="light">{f.type}</Badge></Table.Td><Table.Td><Button size="xs" variant="light" loading={busy===f.code} disabled={!!busy&&busy!==f.code} leftSection={<IconDownload size={14}/>} onClick={()=>importFund(f.code)}>{p.workspace.funds.some(x=>x.fund_id===`CN-${f.code}`)?'更新快照':'接入研究'}</Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer>}
      {receipt&&<Alert color="teal" title="历史数据已入库，可进入经理跟踪与研究副驾">
        <Text size="sm">{receipt.imported} 个观测 · {receipt.start} — {receipt.end}</Text>
        <Text size="xs" mt="xs">{receipt.manifest.return_basis}</Text>
        <Text size="xs" mt="xs">抓取于 {receipt.manifest.retrieved_at} · {receipt.manifest.cache_stale?'旧缓存（网络更新失败）':'有效缓存'}</Text>
        <Text size="xs" style={{overflowWrap:'anywhere'}}>SHA-256：{receipt.manifest.sha256}</Text>
        <Group mt="sm"><Button size="xs" onClick={()=>p.setPage('managers')}>研究该基金</Button><Anchor size="xs" href={receipt.manifest.source_url} target="_blank" rel="noreferrer">查看数据原文 <IconExternalLink size={12}/></Anchor></Group>
      </Alert>}
      <SimpleGrid cols={{base:1,sm:3}}><div><Text fw={600} size="sm">01 · 历史表现</Text><Text size="xs" c="dimmed">计算收益、风险和回撤恢复，不把累计净值当复权净值。</Text></div><div><Text fw={600} size="sm">02 · 原始披露</Text><Text size="xs" c="dimmed">在资料库导入管理人报告 PDF、Word 或文本，保留段落与页码。</Text></div><div><Text fw={600} size="sm">03 · 证据闭环</Text><Text size="xs" c="dimmed">运行陈述审计、追问缺口并导出简报；未取得的持仓和人员信息保持缺失。</Text></div></SimpleGrid>
    </Stack>
  </Panel>;
}

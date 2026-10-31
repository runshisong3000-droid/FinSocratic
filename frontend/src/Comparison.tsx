import { useState } from 'react';
import { Alert, Badge, Button, Group, MultiSelect, SegmentedControl, SimpleGrid, Table, Text, TextInput } from '@mantine/core';
import { ResponsiveContainer, LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend } from 'recharts';
import { IconArrowsExchange } from '@tabler/icons-react';
import { Panel, PageHeading, Empty } from './components';
import { pct, colors } from './utils';
import type { PageProps } from './pages';

export function Comparison(p: PageProps) {
  const [scope,setScope] = useState(p.fund.is_sample?'sample':'real');
  const [ids,setIds] = useState<string[]>([]);
  const [start,setStart] = useState(''); const [end,setEnd] = useState('');
  const [result,setResult] = useState<any>(null); const [busy,setBusy] = useState(false); const [error,setError] = useState('');
  const candidates = p.workspace.funds.filter(f=>!!f.is_sample===(scope==='sample'));
  async function run() {
    setBusy(true); setError(''); setResult(null);
    try {
      const response=await fetch('/api/comparison',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fund_ids:ids,start:start||null,end:end||null})});
      const data=await response.json(); if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'请选择2—8只基金并检查日期'); setResult(data);
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  function invalidate(){setResult(null);setError('');}
  return <><PageHeading eyebrow="COMPARATIVE RESEARCH" title="同区间基金比较" description="先对齐观测日期，再比较收益与风险，避免不同历史长度带来的误判。"/>
    <Panel title="设定研究范围" subtitle="最多8只基金 · 不混合真实数据与合成案例">
      <SegmentedControl mb="md" value={scope} onChange={v=>{setScope(v);setIds([]);invalidate();}} data={[{label:'公开 / 导入基金',value:'real'},{label:'合成演示',value:'sample'}]}/>
      <MultiSelect label="候选基金" placeholder="选择至少两只基金" searchable data={candidates.map(f=>({value:f.fund_id,label:f.name}))} value={ids} onChange={v=>{setIds(v);invalidate();}} maxValues={8}/>
      <SimpleGrid cols={{base:1,sm:2}} my="md"><TextInput type="date" label="开始日期（可选）" value={start} onChange={e=>{setStart(e.currentTarget.value);invalidate();}}/><TextInput type="date" label="结束日期（可选）" value={end} onChange={e=>{setEnd(e.currentTarget.value);invalidate();}}/></SimpleGrid>
      <Group><Button loading={busy} disabled={ids.length<2} onClick={run} leftSection={<IconArrowsExchange size={16}/>}>对齐并计算</Button><Text size="xs" c="dimmed">只保留全部基金共同存在的日期，不填补缺失净值。</Text></Group>
      {candidates.length<2&&<Alert mt="md" color="blue">此范围不足两只基金。前往“数据导入”接入另一只基金，或切换合成演示。</Alert>}
    </Panel>
    {error&&<Alert color="red" mt="md">{error}</Alert>}
    {!result&&!error&&<Empty title="用一致的样本提出更好的问题" description="选定基金后，系统会重新计算共同期间的指标，而不是拼接各自的历史排名。"/>}
    {result&&<><Panel className="section-gap" title="同区间净值路径" subtitle={`${result.start} — ${result.end}`} action={<Badge>{result.observations} 个共同观测</Badge>}><ResponsiveContainer width="100%" height={300}><LineChart data={result.chart}><CartesianGrid vertical={false} stroke="#e9eef3"/><XAxis dataKey="date" minTickGap={60} tick={{fontSize:11}}/><YAxis domain={['auto','auto']} tick={{fontSize:11}}/><Tooltip/><Legend/>{result.funds.map((f:any,i:number)=><Line key={f.fund_id} dataKey={f.fund_id} name={f.name} stroke={colors[i%colors.length]} dot={false} strokeWidth={2}/>)}</LineChart></ResponsiveContainer></Panel>
      <Panel className="section-gap" title="共同样本重算结果" subtitle={result.method}><Table.ScrollContainer minWidth={700}><Table><Table.Thead><Table.Tr>{['基金','区间收益','年化收益','年化波动','最大回撤','采样频率','排除观测'].map(s=><Table.Th key={s}>{s}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{result.funds.map((f:any)=><Table.Tr key={f.fund_id}><Table.Td>{f.name}</Table.Td><Table.Td>{pct(f.metrics.total_return)}</Table.Td><Table.Td>{pct(f.metrics.annual_return)}</Table.Td><Table.Td>{pct(f.metrics.volatility)}</Table.Td><Table.Td>{pct(f.metrics.max_drawdown)}</Table.Td><Table.Td>{f.metrics.frequency}</Table.Td><Table.Td>{f.excluded_observations}</Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer><Alert color="orange" mt="md">{result.limits.join(' ')}</Alert></Panel></>}
  </>;
}

import { useEffect, useState } from 'react';
import { Alert, Anchor, Badge, Button, Group, Progress, SimpleGrid, Table, Text } from '@mantine/core';
import { IconDatabase, IconFileText, IconRefresh, IconChartLine } from '@tabler/icons-react';
import { PageHeading, Panel, Metric } from './components';
import type { PageProps } from './pages';

export function DataHub(p: PageProps) {
 const [data,setData]=useState<any>(null); const [error,setError]=useState('');const [starting,setStarting]=useState(false);
 async function load(){try{const r=await fetch('/api/data-hub');if(!r.ok)throw new Error('读取采集记录失败');setData(await r.json());}catch(e:any){setError(e.message);}}
 useEffect(()=>{load();const timer=window.setInterval(load,4000);return()=>window.clearInterval(timer);},[]);
 async function collect(){setStarting(true);setError('');try{const r=await fetch('/api/data-hub/collect',{method:'POST'});if(!r.ok)throw new Error('启动采集失败');await load();}catch(e:any){setError(e.message);}finally{setStarting(false);}}
 const items=data?.items||[];const nav=items.filter((i:any)=>i.kind==='净值'&&i.status==='ready');const docs=items.filter((i:any)=>i.kind!=='净值'&&i.status==='ready');const failed=items.filter((i:any)=>i.status==='failed');
 return <><PageHeading eyebrow="PUBLIC RESEARCH LIBRARY" title="真实数据中心" description="从公开数据到原始披露，保留每次获取的来源、覆盖范围和失败记录。" action={<Button loading={starting||data?.state==='running'} leftSection={<IconRefresh size={16}/>} onClick={collect}>更新研究数据池</Button>}/>
 {error&&<Alert color="red">{error}</Alert>}
 <SimpleGrid cols={{base:2,lg:4}}><Metric label="真实基金" value={nav.length} detail="代码级历史净值档案" icon={<IconDatabase size={18}/>}/><Metric label="日频观测" value={nav.reduce((n:number,i:any)=>n+i.observations,0).toLocaleString()} detail="已入库，可比较与复算" icon={<IconChartLine size={18}/>}/><Metric label="原始披露" value={docs.length} detail={`${docs.reduce((n:number,i:any)=>n+i.pages,0)} 个可检索PDF页面`} icon={<IconFileText size={18}/>}/><Metric label="采集失败" value={failed.length} detail="保留原因，可再次更新重试" icon={<IconRefresh size={18}/>} color="orange"/></SimpleGrid>
 <Panel className="section-gap" title="采集与存储" action={<Badge color={data?.state==='running'?'blue':'teal'}>{data?.state==='running'?'采集中':data?.state==='complete'?'本轮采集结束':'等待采集'}</Badge>}>
 <Progress value={data?.total?items.length/data.total*100:0} animated={data?.state==='running'} mb="sm"/><Text size="sm">{items.length} / {data?.total||0} 项已处理 · {data?.storage}</Text><Text size="xs" c="dimmed" mt="xs">原始PDF、净值CSV和获取记录保存在D盘数据目录。第三方镜像与管理人官网分别标注；目录选取不代表基金推荐。</Text><Button variant="light" size="xs" mt="md" onClick={async()=>{await load();await p.refresh();p.notify('工作区已更新');}}>将最新数据刷新到工作台</Button>
 </Panel>
 <Panel className="section-gap" title="原始披露档案" subtitle="历史年报、季报、中报及招募说明书；报告期与抓取时间分别保留">
 <Table.ScrollContainer minWidth={750}><Table highlightOnHover><Table.Thead><Table.Tr><Table.Th>材料</Table.Th><Table.Th>报告基准日</Table.Th><Table.Th>来源</Table.Th><Table.Th>页数</Table.Th><Table.Th>操作</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{docs.map((i:any)=><Table.Tr key={i.id}><Table.Td><Text size="sm" fw={600}>{i.title}</Text><Text size="xs" c="dimmed">{i.code} · {i.kind}</Text></Table.Td><Table.Td>{i.date}</Table.Td><Table.Td><Anchor href={i.url} target="_blank" size="xs">{i.provider}</Anchor></Table.Td><Table.Td>{i.pages}</Table.Td><Table.Td><Group gap="xs"><Button size="xs" variant="light" onClick={()=>p.openDoc(i.document_id)}>检索原文</Button><Anchor href={`/api/documents/${i.document_id}/original`} target="_blank" size="xs">本地PDF</Anchor></Group></Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer>
 </Panel>
 <Panel className="section-gap" title="基金历史覆盖" subtitle="来源日涨跌幅连乘指数；源数据复权处理尚未独立调节">
 <Table.ScrollContainer minWidth={700}><Table highlightOnHover><Table.Thead><Table.Tr><Table.Th>基金</Table.Th><Table.Th>数据区间</Table.Th><Table.Th>观测</Table.Th><Table.Th>抓取时间</Table.Th><Table.Th/></Table.Tr></Table.Thead><Table.Tbody>{nav.map((i:any)=><Table.Tr key={i.id}><Table.Td><Text size="sm" fw={600}>{i.name}</Text><Anchor size="xs" href={i.source_url} target="_blank">{i.id} · 数据源</Anchor></Table.Td><Table.Td>{i.start}<br/>{i.end}</Table.Td><Table.Td>{i.observations}</Table.Td><Table.Td><Text size="xs">{new Date(i.retrieved_at).toLocaleString('zh-CN')}</Text>{i.cache_stale&&<Badge color="orange">旧缓存</Badge>}</Table.Td><Table.Td><Button size="xs" variant="subtle" onClick={()=>{p.setFund(`CN-${i.id}`);p.setPage('managers');}}>研究</Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer>
 </Panel>{failed.length>0&&<Panel className="section-gap" title="需要重试的来源">{failed.map((i:any)=><Alert key={i.id} color="orange" mb="xs" title={i.title||i.id}>{i.error}</Alert>)}</Panel>}</>;
}

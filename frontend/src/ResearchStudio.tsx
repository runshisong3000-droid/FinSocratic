import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, Select, Stack, Text, Textarea, Paper, Loader, Accordion, FileInput } from '@mantine/core';
import { IconArrowUp, IconSparkles, IconPlus, IconFileText, IconDownload, IconCheck } from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { LearningEvidence } from './LearningEvidence';

async function request(path:string,body?:unknown){
 const response=await fetch(`/api/research/${path}`,body?{signal:AbortSignal.timeout(20000),method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{signal:AbortSignal.timeout(20000)});
 const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'研究服务暂时不可用');return data;
}
const mandate="【完整尽调委托】请完成这只基金的全面证据尽调，核对收益、回撤、任职、底层持仓、贝叶斯稳健性及神经网络验证，主动寻找反证，交付完整研究报告和下一步访谈提纲。";
const starters=['这只基金的历史表现，能支持经理声称的投资能力吗？','从原始报告里找出最值得追问的三个问题，并说明需要哪些证据。','这只基金最深的回撤是怎么发生的？现有材料能解释吗？'];

export function ResearchStudio({openDoc}:{openDoc:(id:string)=>void}){
 const [attachment,setAttachment]=useState<File|null>(null);const [uploading,setUploading]=useState(false);const [uploadNotice,setUploadNotice]=useState('');
 const [funds,setFunds]=useState<any[]>([]);const [sessions,setSessions]=useState<any[]>([]);const [model,setModel]=useState<any>(null);
 const [fundId,setFundId]=useState('');const [sessionId,setSessionId]=useState<string|null>(null);const [conversation,setConversation]=useState<any>(null);
 const [question,setQuestion]=useState('');const [error,setError]=useState('');const [submitting,setSubmitting]=useState(false);const [loading,setLoading]=useState(true);
 async function bootstrap(){const data=await request('bootstrap');setFunds(data.funds);setSessions(data.sessions);setModel(data.model);setFundId(prev=>prev||data.funds.find((f:any)=>f.fund_id==='CN-005218')?.fund_id||data.funds[0]?.fund_id||'');}
 useEffect(()=>{bootstrap().catch(e=>setError(e.message)).finally(()=>setLoading(false));},[]);
 const running=conversation?.turns?.some((t:any)=>t.state==='running')||submitting;
 useEffect(()=>{
   if(!sessionId)return;
   let cancelled=false;
   async function poll(){try{const next=await request(`sessions/${sessionId}`);if(!cancelled)setConversation(next);}catch(e:any){if(!cancelled)setError(e.message);}}
   poll();const timer=window.setInterval(poll,2000);return()=>{cancelled=true;window.clearInterval(timer);};
 },[sessionId]);
 async function send(value=question){
   if(!value.trim()||running)return;setSubmitting(true);setError('');
   try{const r=await request('ask',{question:value.trim(),fund_id:fundId,session_id:sessionId});setSessionId(r.session_id);setConversation(await request(`sessions/${r.session_id}`));setQuestion('');await bootstrap();}
   catch(e:any){setError(e.message);}finally{setSubmitting(false);}
 }
 async function addEvidence(){if(!attachment||running)return;setUploading(true);setError('');try{const form=new FormData();form.append('file',attachment);form.append('fund_id',fundId);form.append('period','reference');const response=await fetch('/api/documents',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw new Error(data.detail||'资料导入失败');setAttachment(null);setUploadNotice(`已入库：${data.name}，${data.chunks_count} 个提取片段。点击更新判断将使用新资料，原件归档在D盘。`);}catch(e:any){setError(e.message);}finally{setUploading(false);}}
 function newChat(){if(running)return;setSessionId(null);setConversation(null);setQuestion('');setError('');}
 async function resume(id:string|null){if(!id||running)return;try{const c=await request(`sessions/${id}`);setFundId(c.fund_id);setConversation(c);setSessionId(id);setError('');}catch(e:any){setError(e.message);}}
 function download(turn:any){const p=turn.payload;const text=`# ${turn.question}\n\n${p.answer}\n\n## 研究版本与变化\n\n${p.evidence_delta?.summary||"历史记录未保存输入快照"}\n\n${p.judgment?.change||""}\n\n## 证据来源\n\n`+(p.citations||[]).map((c:any)=>`- [${c.id}] ${c.source} · ${c.location}\n\n${c.text}`).join('\n\n');const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='FinSocratic_AI研究记录.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 const selected=funds.find(f=>f.fund_id===fundId);
 return <div className="research-studio">
  <Group justify="space-between" mb="lg"><Group gap="xs"><div className="studio-spark"><IconSparkles size={22}/></div><div><Text fw={700}>FinSocratic Research</Text><Text size="xs" c="dimmed">FOF 经理证据研究助手</Text></div></Group><Badge color={model?.available?'teal':'gray'} variant="light">{model?.available?'DeepSeek 已配置':'等待模型配置'}</Badge></Group>
  <div className="studio-context"><Select label="研究对象" searchable value={fundId} disabled={running||!!sessionId} onChange={v=>v&&setFundId(v)} data={funds.map(f=>({value:f.fund_id,label:`${f.name} · ${f.fund_id}`}))}/><Select label="继续历史研究" placeholder="选择已保存的会话" value={sessionId} disabled={running} searchable onChange={resume} data={sessions.map(s=>({value:s.id,label:s.title}))}/><Button variant="subtle" leftSection={<IconPlus size={16}/>} disabled={running} onClick={newChat}>新研究</Button></div>
  {loading&&<Group justify="center" py="xl"><Loader size="sm"/><Text>正在打开研究空间…</Text></Group>}
  {sessionId&&<Paper p="md" mt="md" withBorder radius="md"><Text fw={650}>为当前研究补充证据</Text><Group mt="sm"><FileInput aria-label="新增研究资料" placeholder="选择 PDF、DOCX 或 TXT" accept=".pdf,.docx,.txt,.md" value={attachment} onChange={setAttachment} disabled={running||uploading}/><Button onClick={addEvidence} loading={uploading} disabled={!attachment||running}>入库并归档原件</Button></Group>{uploadNotice&&<Text size="sm" mt="sm">{uploadNotice}</Text>}<Text size="xs" c="dimmed" mt="xs">下一轮研究会将必要内容发送给 DeepSeek；入库本身不会启动模型。</Text></Paper>}
  {error&&<Alert color="red" my="md">{error}</Alert>}
  {!loading&&<Paper p="lg" mt="md" withBorder radius="lg"><Group justify="space-between"><div><Text fw={750} size="lg">委派一项完整研究</Text><Text size="sm" c="dimmed">净值复算 → 持仓核对 → 模型证据 → 补证 → 报告 → 论断核验</Text></div><Button disabled={running||!model?.available} loading={running} onClick={()=>send(mandate)}>生成完整尽调报告</Button></Group><Text size="xs" mt="sm" c="dimmed">使用当前已入库资料，缺失项列为待办；不会把缺证据的章节伪装成已完成。研究过程和结果自动保存在 D 盘。</Text></Paper>}
  {!conversation&&!loading&&<div className="studio-welcome"><Badge variant="outline" color="teal">FOF MANAGER INTELLIGENCE</Badge><h1>把研究任务交给我。</h1><p>从 {selected?.name||'基金经理'} 开始。提出问题，我会查找披露、复算数据、寻找反证，并告诉你还有哪些证据不足。</p><div className="studio-starters">{starters.map((s,i)=><button key={s} disabled={running||!model?.available} onClick={()=>send(s)}><span>0{i+1}</span>{s}<IconArrowUp size={16}/></button>)}</div></div>}
  {!loading&&fundId&&<Accordion mt="md" variant="contained"><Accordion.Item value="models"><Accordion.Control>研究工具与模型证据 · 按需展开</Accordion.Control><Accordion.Panel><LearningEvidence fundId={fundId} onAsk={setQuestion}/></Accordion.Panel></Accordion.Item></Accordion>}
  {sessionId&&<Button component="a" href={`/api/research/sessions/${sessionId}/print`} target="_blank" variant="outline" mt="md">打开可打印研究档案 · 含历史版本</Button>}
  <Stack gap="xl" mt="lg">{conversation?.turns?.map((turn:any)=>{const p=turn.payload||{};return <div key={turn.id} className="studio-turn"><div className="studio-user">{turn.question}</div>
   <div className="studio-response"><Group gap="xs" mb="md"><IconSparkles size={18}/><Text fw={650}>FinSocratic</Text><Text size="xs" c="dimmed">{p.model||model?.model}</Text>{turn.state==='running'&&<Loader size="xs"/>}</Group>
    <Accordion variant="contained" radius="md" defaultValue={turn.state==='running'?'steps':null} mb="md"><Accordion.Item value="steps"><Accordion.Control>{turn.state==='running'?'正在研究':turn.state==='failed'?'研究未完成':'查看调查过程'} · {p.steps?.length||0} 个已记录步骤</Accordion.Control><Accordion.Panel><Stack gap="sm">{(p.steps||[]).map((s:any,i:number)=><Group key={i} align="flex-start" wrap="nowrap"><IconCheck size={15} color="#139c83"/><div><Text size="sm" fw={600}>{s.label}</Text><Text size="xs" c="dimmed">{s.detail}</Text></div></Group>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>
    {turn.state==='running'&&<Text size="sm" c="dimmed">{p.steps?.at(-1)?.detail||'任务已提交，正在准备研究上下文…'}</Text>}
    {p.evidence_gap&&<Alert color="blue" mb="md" title="本轮发现的证据缺口">{p.evidence_gap}</Alert>}
    {p.error&&<Alert color="orange">{p.error}<Button size="xs" variant="subtle" onClick={()=>setQuestion(turn.question)}>重新编辑问题</Button></Alert>}
    {p.evidence_delta&&<Paper withBorder p="md" mb="md" radius="md"><Group justify="space-between"><Text fw={700}>研究版本 V{p.version||1}</Text><Badge color={p.evidence_delta.status==='changed'?'orange':'teal'}>{p.evidence_delta.status==='changed'?'输入有更新':p.evidence_delta.status==='baseline'?'首次基线':'输入未变'}</Badge></Group><Text size="sm" mt="xs">{p.evidence_delta.summary}</Text>{p.evidence_delta.changes?.map((c:any)=><Text size="xs" key={c.category}>• {c.category}：{c.before?.rows??c.before?.run_id??'原版本'} → {c.after?.rows??c.after?.run_id??'新版本'}</Text>)}{p.judgment&&<><Text mt="md" fw={650}>{p.judgment.hypothesis}</Text><Text mt="xs">{p.judgment.conclusion}</Text><Text size="sm" c="dimmed" mt="xs">{p.judgment.change}</Text><Group mt="sm" align="flex-start"><div><Text fw={600} size="sm">支持证据</Text>{p.judgment.support?.map((v:string)=><Text key={v} size="xs">{v}</Text>)}</div><div><Text fw={600} size="sm">反证与限制</Text>{p.judgment.counter?.map((v:string)=><Text key={v} size="xs">{v}</Text>)}</div></Group><Text fw={600} size="sm" mt="md">下一步补证</Text>{p.judgment.next_actions?.map((v:string)=><Text key={v} size="sm">• {v}</Text>)}</>}<Button mt="md" size="xs" variant="light" disabled={running} onClick={()=>send('请延续当前研究假设，重新核对已入库的新资料，比较上轮证据和判断，明确哪些改变、哪些未改变；没有新证据时不要声称变化。')}>用最新入库证据更新判断</Button></Paper>}
    {p.answer&&<><div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{p.answer}</ReactMarkdown></div><Text size="xs" c="dimmed" mt="md">{p.boundary}</Text><Group mt="md"><Button variant="subtle" size="xs" leftSection={<IconDownload size={14}/>} onClick={()=>download(turn)}>导出本轮研究</Button><Badge color="gray" variant="light">{p.citations?.length||0} 条可定位证据</Badge></Group></>}
    {!!p.citations?.length&&<Accordion mt="md" variant="separated" radius="md">{p.citations.map((c:any)=><Accordion.Item key={c.id} value={c.id}><Accordion.Control><Group gap="xs"><Badge size="sm" variant="light">{c.id}</Badge><Text size="sm">{c.source} · {c.location}</Text></Group></Accordion.Control><Accordion.Panel><Text size="xs" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:260,overflow:'auto'}}>{c.text}</Text>{c.document_id&&<Button size="xs" variant="light" mt="sm" leftSection={<IconFileText size={14}/>} onClick={()=>openDoc(c.document_id)}>查看完整材料</Button>}</Accordion.Panel></Accordion.Item>)}</Accordion>}
    {!!p.suggestions?.length&&<Group mt="lg" gap="xs">{p.suggestions.map((s:string)=><Button key={s} variant="light" size="xs" h="auto" py={7} style={{whiteSpace:'normal'}} onClick={()=>setQuestion(s)}>{s}</Button>)}</Group>}
   </div></div>;})}</Stack>
  <Paper className="studio-composer" withBorder radius="lg" p="md" mt="xl"><Textarea variant="unstyled" autosize minRows={2} maxRows={6} placeholder={sessionId?'继续追问：这个判断还能有哪些解释？':'提出一个具体研究问题…'} value={question} onChange={e=>setQuestion(e.currentTarget.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();send();}}}/><Group justify="space-between" mt="sm"><Text size="xs" c="dimmed">问题与必要证据发送至 DeepSeek · Ctrl+Enter 提交</Text><Button radius="xl" disabled={!question.trim()||!model?.available||running} loading={running} rightSection={<IconArrowUp size={16}/>} onClick={()=>send()}>开始研究</Button></Group></Paper>
 </div>;
}

import { useEffect, useState } from 'react';
import {
  Badge, Button, Group, Text, Drawer, Modal, Select, MultiSelect, FileInput,
  Textarea, Loader, Alert, ActionIcon, Tooltip, ScrollArea, Divider, Stack,
  Paper, TextInput, Switch,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconLayoutDashboard, IconBuildingBank, IconShieldCheck, IconListCheck,
  IconFileText, IconDatabase, IconSparkles, IconRefresh, IconPlus,
  IconFlask, IconX, IconFileUpload, IconArrowRight,
} from '@tabler/icons-react';
import { Overview, Managers, Audit, type PageProps } from './pages';
import { TasksPage, DocumentsPage, DataPage, CopilotPage } from './workspace';
import { Empty } from './components';
import { Comparison } from './Comparison';
import { DataHub } from './DataHub';
import { ResearchStudio } from './ResearchStudio';
import { getWorkspace, getRun, createRun, getDocument, runDemo } from './api';
import type { Workspace, Run, Evidence, DocumentSummary, Fund } from './types';
import { timeText } from './utils';

const NAV = [
  { id: 'copilot', label: 'AI 研究', icon: IconSparkles },
  { id: 'overview', label: '总览', icon: IconLayoutDashboard },
  { id: 'managers', label: '经理跟踪', icon: IconBuildingBank },
  { id: 'comparison', label: '基金比较', icon: IconLayoutDashboard },
  { id: 'audit', label: '尽调审计', icon: IconShieldCheck },
  { id: 'tasks', label: '研究待办', icon: IconListCheck },
  { id: 'documents', label: '资料库', icon: IconFileText },
  { id: 'hub', label: '真实数据', icon: IconDatabase },
  { id: 'data', label: '数据导入', icon: IconDatabase },
];

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [fundId, setFundId] = useState('');
  const [page, setPage] = useState('copilot');
  const [evidenceTarget, setEvidenceTarget] = useState<{ evidence: Evidence; run?: Run } | null>(null);
  const [docTarget, setDocTarget] = useState<DocumentSummary | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const ws = await getWorkspace();
      setWorkspace(ws);
      setFundId((prev) => (prev && ws.funds.some((f) => f.fund_id === prev) ? prev : (ws.funds[0]?.fund_id || '')));
      setRun(ws.latest_run || null);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if(page !== 'copilot' && !workspace) load();
  }, [page]);

  function notify(message: string, isError = false) {
    notifications.show({ title: isError ? '操作失败' : '已完成', message, color: isError ? 'red' : 'teal' });
  }

  async function refresh() {
    try {
      const ws = await getWorkspace();
      setWorkspace(ws);
      setFundId((prev) => (prev && ws.funds.some((f) => f.fund_id === prev) ? prev : (ws.funds[0]?.fund_id || '')));
    } catch (e: any) {
      notify(e.message, true);
    }
    if (run?.id) {
      try {
        setRun(await getRun(run.id));
      } catch {
        /* 保留现有审计 */
      }
    }
  }

  function setFund(id: string) {
    setFundId(id);
    setRun((prev) => (prev && prev.fund.fund_id === id ? prev : null));
  }

  async function openRun(id: string) {
    try {
      const r = await getRun(id);
      setRun(r);
      setFundId(r.fund.fund_id);
      setPage('audit');
    } catch (e: any) {
      notify(e.message, true);
    }
  }

  function openEvidence(evidence: Evidence, currentRun?: Run) {
    setEvidenceTarget({ evidence, run: currentRun });
  }

  async function openDoc(id: string) {
    try {
      setDocTarget(await getDocument(id));
    } catch (e: any) {
      notify(e.message, true);
    }
  }

  async function runDemoNow() {
    setDemoBusy(true);
    try {
      const r = await runDemo();
      setRun(r);
      setFundId(r.fund.fund_id);
      setPage('audit');
      notify('合成演示审计已生成');
      await refresh();
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setDemoBusy(false);
    }
  }

  const fund: Fund | undefined = workspace?.funds.find((f) => f.fund_id === fundId) ?? workspace?.funds[0];

  const pageProps: PageProps | null = workspace && fund
    ? {
        workspace, run, fund, fundId,
        setFund, openRun, openNew: () => setNewOpen(true), openEvidence, openDoc,
        refresh, setPage, notify,
      }
    : null;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-mark"><IconShieldCheck size={22} /></div>
          <div><div className="logo-name">FinSocratic</div><div className="logo-sub">FOF 投研工作台</div></div>
        </div>
        <ScrollArea className="sidebar-scroll">
          <nav className="sidebar-nav">
            {NAV.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}>
                  <Icon size={18} /><span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </ScrollArea>
        <div className="sidebar-footer">
          {workspace?.demo_mode && <Badge color="orange" variant="light" size="sm">合成演示数据</Badge>}
          <Text size="xs" c="dimmed">本机研究 · 无实时行情</Text>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <Text size="xs" c="dimmed" fw={600}>{page === 'overview' ? 'RESEARCH WORKBENCH' : NAV.find((n) => n.id === page)?.label?.toUpperCase() || 'WORKSPACE'}</Text>
            <Text size="sm" fw={600}>证据优先的 FOF 经理尽调与审计</Text>
          </div>
          {page !== "copilot" && <Group gap="xs">
            <Tooltip label="重新加载工作区"><ActionIcon variant="subtle" onClick={load} aria-label="刷新"><IconRefresh size={18} /></ActionIcon></Tooltip>
            <Button variant="light" leftSection={<IconFlask size={16} />} loading={demoBusy} onClick={runDemoNow}>运行演示</Button>
            <Button leftSection={<IconPlus size={16} />} onClick={() => setNewOpen(true)}>新建尽调</Button>
          </Group>}
        </header>

        <main className="content">
          {page === "copilot" ? <ResearchStudio openDoc={openDoc}/> : <>
          {loading && <Group justify="center" py="xl"><Loader /><Text c="dimmed" size="sm">正在加载工作区…</Text></Group>}
          {!loading && error && (
            <Alert color="red" icon={<IconX size={16} />} title="无法连接后端">
              {error}。请确认 FastAPI 已在 8501 端口运行（python -m finsocratic.api）。
            </Alert>
          )}
          {!loading && !error && !pageProps && (
            <Empty title="工作区为空" description="导入基金档案或运行演示案例后即可开始研究。" action={<Button onClick={runDemoNow}>运行演示案例</Button>} />
          )}
          {!loading && !error && pageProps && (() => {
            switch (page) {
              case 'managers': return <Managers {...pageProps} />;
              case 'audit': return <Audit {...pageProps} />;
              case 'tasks': return <TasksPage {...pageProps} />;
              case 'documents': return <DocumentsPage {...pageProps} />;
              case 'data': return <DataPage {...pageProps} />;
              case 'comparison': return <Comparison {...pageProps} />;
              case 'hub': return <DataHub {...pageProps} />;
              case 'copilot': return <CopilotPage {...pageProps} />;
              default: return <Overview {...pageProps} />;
            }
          })()}
          </>}
        </main>
      </div>

      <EvidenceDrawer target={evidenceTarget} onClose={() => setEvidenceTarget(null)} />
      <DocumentDrawer doc={docTarget} onClose={() => setDocTarget(null)} />
      <NewRunModal
        open={newOpen}
        onClose={() => setNewOpen(false)}
        initialFundId={fundId}
        funds={workspace?.funds || []}
        documents={workspace?.documents || []}
        notify={notify}
        onDone={(r) => {
          setNewOpen(false);
          setRun(r);
          setFundId(r.fund.fund_id);
          setPage('audit');
          refresh();
        }}
      />
    </div>
  );
}

function EvidenceDrawer({ target, onClose }: { target: { evidence: Evidence; run?: Run } | null; onClose: () => void }) {
  const evidence = target?.evidence;
  return (
    <Drawer opened={!!evidence} onClose={onClose} position="right" size="lg" title="证据详情">
      {evidence && (
        <Stack gap="md">
          <Group justify="space-between">
            <Badge color="teal" variant="light">{evidence.kind}</Badge>
            <Text size="xs" c="dimmed" className="tabular">{evidence.id}</Text>
          </Group>
          <div>
            <Text size="xs" c="dimmed" fw={600}>来源</Text>
            <Text size="sm" fw={550}>{evidence.source}</Text>
            <Text size="xs" c="dimmed">{evidence.location}</Text>
          </div>
          <Paper withBorder radius="md" p="md">
            <Text size="sm" lh={1.8}>{evidence.text}</Text>
          </Paper>
          {evidence.input_evidence_ids && evidence.input_evidence_ids.length > 0 && (
            <div>
              <Text size="xs" c="dimmed" fw={600} mb="xs">由以下证据计算得出</Text>
              <Stack gap="xs">
                {evidence.input_evidence_ids.map((id) => (
                  <Badge key={id} variant="outline" size="md" style={{ fontFamily: 'monospace' }}>{id}</Badge>
                ))}
              </Stack>
            </div>
          )}
          {target?.run && (
            <Alert color="gray" icon={<IconArrowRight size={16} />}>来自审计 {target.run.fund.name} · {timeText(target.run.created_at)}</Alert>
          )}
        </Stack>
      )}
    </Drawer>
  );
}

function DocumentDrawer({ doc, onClose }: { doc: DocumentSummary | null; onClose: () => void }) {
  const [query, setQuery] = useState('');
  useEffect(()=>setQuery(''),[doc?.id]);
  const chunks=(doc?.chunks||[]).filter(c=>!query.trim()||c.text.includes(query.trim())||c.location.includes(query.trim()));
  return (
    <Drawer opened={!!doc} onClose={onClose} position="right" size="lg" title="资料详情">
      {doc && (
        <Stack gap="md">
          <Group justify="space-between">
            <div>
              <Text fw={650}>{doc.name}</Text>
              <Text size="xs" c="dimmed">{doc.fund_id} · {doc.period === 'current' ? '现期' : doc.period === 'prior' ? '前期' : '参考'} · 加入于 {timeText(doc.added_at)}</Text>
            </div>
            <Badge variant="light" color="gray">{doc.chunks?.length || 0} 个片段</Badge>
          </Group>
          <TextInput label="查找原文或页码" placeholder="例如：业绩、经理、第 8 页" value={query} onChange={e=>setQuery(e.currentTarget.value)}/>
          <Text size="xs" c="dimmed">{chunks.length} 个匹配片段 · PDF 页码为物理页码</Text>
          <Divider />
          <ScrollArea h="65vh">
            <Stack gap="md">
              {chunks.map((chunk, i) => (
                <Paper key={i} withBorder radius="md" p="md">
                  <Group gap="xs" mb={8}><IconFileText size={14} /><Badge size="xs" variant="light" color="teal">{chunk.location}</Badge></Group>
                  <Text size="sm" lh={1.8}>{chunk.text}</Text>
                </Paper>
              ))}
              {!chunks.length && <Empty title="没有匹配片段" description="请调整关键词或页码。" />}
            </Stack>
          </ScrollArea>
        </Stack>
      )}
    </Drawer>
  );
}

function NewRunModal({ open, onClose, funds, documents, notify, onDone, initialFundId }: {
  initialFundId: string;
  open: boolean; onClose: () => void; funds: Fund[]; documents: DocumentSummary[];
  notify: (m: string, e?: boolean) => void; onDone: (r: Run) => void;
}) {
  const [fundId, setFundId] = useState('');
  const [report, setReport] = useState<File | null>(null);
  const [priorReport, setPriorReport] = useState<File | null>(null);
  const [benchmark, setBenchmark] = useState<File | null>(null);
  const [extraText, setExtraText] = useState('');
  const [docIds, setDocIds] = useState<string[]>([]);
  const [priorDocIds, setPriorDocIds] = useState<string[]>([]);
  const [useAi, setUseAi] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setFundId(initialFundId || funds[0]?.fund_id || '');
      setReport(null); setPriorReport(null); setBenchmark(null);
      setExtraText(''); setDocIds([]); setPriorDocIds([]); setUseAi(false);
    }
  }, [open, initialFundId]);

  const currentDocs = documents.filter((d) => d.fund_id === fundId && d.period !== 'prior');
  const priorDocs = documents.filter((d) => d.fund_id === fundId && d.period === 'prior');

  async function submit() {
    if (!fundId) { notify('请选择基金', true); return; }
    setSubmitting(true);
    try {
      const r = await createRun({ fundId, report, priorReport, benchmark, extraText, documentIds: docIds, priorDocumentIds: priorDocIds, useAi });
      onDone(r);
    } catch (e: any) {
      notify(e?.message || String(e), true);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal opened={open} onClose={onClose} title="新建尽调任务" size="lg">
      <Stack gap="md">
        <Select
          label="目标基金"
          value={fundId}
          onChange={(v) => setFundId(v || '')}
          data={funds.map((f) => ({ value: f.fund_id, label: `${f.manager} · ${f.name}` }))}
        />
        <Divider label="现期材料" labelPosition="left" />
        <MultiSelect
          label="从资料库选择"
          placeholder={currentDocs.length ? '选择现期报告' : '暂无现期资料，可上传'}
          value={docIds}
          onChange={setDocIds}
          data={currentDocs.map((d) => ({ value: d.id, label: d.name }))}
        />
        <FileInput label="或上传现期报告" placeholder="选择文件" value={report} onChange={setReport} leftSection={<IconFileUpload size={16} />} />
        <Textarea label="或粘贴待核对陈述" placeholder="每行一条陈述…" value={extraText} onChange={(e) => setExtraText(e.currentTarget.value)} autosize minRows={2} maxRows={4} />
        <Divider label="前期材料（跨期对照）" labelPosition="left" />
        <MultiSelect
          label="从资料库选择"
          placeholder={priorDocs.length ? '选择前期报告' : '暂无前期资料'}
          value={priorDocIds}
          onChange={setPriorDocIds}
          data={priorDocs.map((d) => ({ value: d.id, label: d.name }))}
        />
        <FileInput label="或上传前期报告" placeholder="选择文件" value={priorReport} onChange={setPriorReport} leftSection={<IconFileUpload size={16} />} />
        <Divider label="基准（可选）" labelPosition="left" />
        <FileInput label="基准净值序列" placeholder="CSV：date, nav" value={benchmark} onChange={setBenchmark} leftSection={<IconFileUpload size={16} />} />
        <Divider label="AI 增强（可选）" labelPosition="left" />
        <Switch checked={useAi} onChange={(e) => setUseAi(e.currentTarget.checked)} label="启用 DeepSeek 深度研判与红队质疑" description="数字仍由确定性计算生成，模型只做推理与质疑；需已配置 DEEPSEEK_API_KEY。" />
        <Group justify="flex-end" mt="sm">
          <Button variant="default" onClick={onClose}>取消</Button>
          <Button loading={submitting} onClick={submit}>开始尽调</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

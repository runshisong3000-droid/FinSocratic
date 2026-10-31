import { useState } from 'react';
import {
  Badge, Button, Group, Text, Table, Select, SegmentedControl, Stack, TextInput,
  FileInput, SimpleGrid, Alert, Textarea, Loader, Divider, ActionIcon, ThemeIcon, Paper,
} from '@mantine/core';
import {
  IconUpload, IconSearch, IconDatabase, IconFileText, IconSend, IconCheck,
  IconProgress, IconRotateClockwise, IconSparkles, IconFileImport,
  IconArrowRight, IconFolder, IconShieldCheck,
} from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PageHeading, Panel, Empty, Metric } from './components';
import { timeText } from './utils';
import { updateTask, uploadDocument, searchDocuments, importData, askCopilot } from './api';
import type { PageProps } from './pages';
import type { ResearchTask, CopilotResponse } from './types';
import { MarketData } from './MarketData';

const taskStatus: Record<string, { label: string; color: string }> = {
  open: { label: '待处理', color: 'orange' },
  in_progress: { label: '处理中', color: 'blue' },
  resolved: { label: '已解决', color: 'teal' },
};

export function TasksPage(p: PageProps) {
  const tasks = p.workspace.tasks || [];
  const [filter, setFilter] = useState('open');
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Record<string, string>>({});

  const filtered = tasks.filter((t) => (filter === 'all' ? true : t.status === filter));
  const counts = {
    open: tasks.filter((t) => t.status === 'open').length,
    in_progress: tasks.filter((t) => t.status === 'in_progress').length,
    resolved: tasks.filter((t) => t.status === 'resolved').length,
  };

  async function changeStatus(t: ResearchTask, status: ResearchTask['status']) {
    setBusy(t.id);
    try {
      await updateTask(t.id, status, note[t.id] || undefined);
      p.notify(status === 'resolved' ? '任务已标记解决' : '任务状态已更新');
      await p.refresh();
    } catch (e: any) {
      p.notify(e.message, true);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="RESEARCH TASKS"
        title="研究待办"
        description="把每条疑点变成可追踪的下一步，保留处理记录，形成闭环。"
        action={<SegmentedControl value={filter} onChange={setFilter} data={[
          { label: `待处理 ${counts.open}`, value: 'open' },
          { label: `处理中 ${counts.in_progress}`, value: 'in_progress' },
          { label: `已解决 ${counts.resolved}`, value: 'resolved' },
          { label: `全部 ${tasks.length}`, value: 'all' },
        ]} />}
      />
      <SimpleGrid cols={{ base: 1, md: 3 }} className="section-gap">
        <Metric label="待处理" value={counts.open} detail="尚无线索的追问" icon={<IconRotateClockwise size={18} />} color="orange" />
        <Metric label="处理中" value={counts.in_progress} detail="正在补充资料或核对" icon={<IconProgress size={18} />} color="blue" />
        <Metric label="已解决" value={counts.resolved} detail="已记录处理结论" icon={<IconCheck size={18} />} />
      </SimpleGrid>
      <Panel title="跟进清单" subtitle="来自陈述追问与机构尽调清单的缺口" className="section-gap">
        {filtered.length === 0 ? (
          <Empty title="当前没有待办" description="新的尽调会从陈述追问和尽调清单里自动生成跟进项。" />
        ) : (
          <Stack gap="sm">
            {filtered.map((t) => (
              <Paper key={t.id} withBorder radius="md" p="md" className="task-card">
                <Group justify="space-between" align="flex-start">
                  <div style={{ flex: 1 }}>
                    <Group gap="xs" mb={6}>
                      <Badge color={taskStatus[t.status].color} variant="light">{taskStatus[t.status].label}</Badge>
                      <Badge color={t.priority === '高' ? 'red' : 'orange'} variant="outline">{t.priority}优先级</Badge>
                      {t.category && t.category !== 'claim' && <Badge color="gray" variant="light">{t.category}</Badge>}
                    </Group>
                    <Text fw={600}>{t.question}</Text>
                    <Text size="xs" c="dimmed" mt={4}>创建于 {timeText(t.created_at)} · {t.related_claim_ids?.length || 0} 条关联陈述</Text>
                    {t.status === 'resolved' && t.resolution_note && (
                      <Alert mt="sm" color="teal" variant="light" icon={<IconCheck size={16} />}>{t.resolution_note}</Alert>
                    )}
                    {t.status !== 'resolved' && (
                      <Textarea
                        mt="sm"
                        size="xs"
                        placeholder="补充处理备注（可选）"
                        value={note[t.id] || ''}
                        onChange={(e) => setNote((prev) => ({ ...prev, [t.id]: e.currentTarget.value }))}
                      />
                    )}
                  </div>
                  <Group gap="xs" style={{ flexShrink: 0 }}>
                    {t.status === 'open' && (
                      <Button size="xs" variant="light" leftSection={<IconProgress size={14} />} loading={busy === t.id} onClick={() => changeStatus(t, 'in_progress')}>开始处理</Button>
                    )}
                    {t.status === 'in_progress' && (
                      <Button size="xs" leftSection={<IconCheck size={14} />} loading={busy === t.id} onClick={() => changeStatus(t, 'resolved')}>标记解决</Button>
                    )}
                    {t.status === 'resolved' && (
                      <Button size="xs" variant="default" loading={busy === t.id} onClick={() => changeStatus(t, 'open')}>重新打开</Button>
                    )}
                  </Group>
                </Group>
              </Paper>
            ))}
          </Stack>
        )}
      </Panel>
    </>
  );
}

export function DocumentsPage(p: PageProps) {
  const docs = p.workspace.documents || [];
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{ document_id: string; source: string; fund_id: string; location: string; text: string; score: number }[] | null>(null);
  const [notice, setNotice] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [period, setPeriod] = useState('current');
  const [uploading, setUploading] = useState(false);
  const [searching, setSearching] = useState(false);

  async function doSearch() {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const res = await searchDocuments(q.trim(), p.fundId);
      setResults(res.results);
      setNotice(res.notice || '');
    } catch (e: any) {
      p.notify(e.message, true);
    } finally {
      setSearching(false);
    }
  }

  async function doUpload() {
    if (!file) { p.notify('请先选择文件', true); return; }
    setUploading(true);
    try {
      const doc = await uploadDocument(file, p.fundId, period);
      p.notify(`已导入资料「${doc.name}」，共 ${doc.chunks_count || 0} 个片段`);
      setFile(null);
      await p.refresh();
    } catch (e: any) {
      p.notify(e.message, true);
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      <PageHeading eyebrow="DOCUMENT LIBRARY" title="资料库" description="报告原文、持仓与净值口径统一沉淀，支持全文检索与逐段溯源。" />
      <SimpleGrid cols={{ base: 1, md: 3 }} className="section-gap">
        <Metric label="资料总数" value={docs.length} detail="全部基金与期间" icon={<IconFileText size={18} />} color="indigo" />
        <Metric label="现期材料" value={docs.filter((d) => d.period === 'current').length} detail="用于最新尽调" icon={<IconFolder size={18} />} />
        <Metric label="前期材料" value={docs.filter((d) => d.period === 'prior').length} detail="用于跨期对照" icon={<IconRotateClockwise size={18} />} color="orange" />
      </SimpleGrid>
      <div className="grid-2-1 section-gap">
        <Panel title="全文检索" subtitle="匹配分数仅表示文字相关性，不代表真实性或因果关系" action={
          <Group gap="xs">
            <TextInput
              w={260}
              leftSection={<IconSearch size={15} />}
              placeholder="搜索陈述、管理人、比例…"
              value={q}
              onChange={(e) => setQ(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch(); }}
            />
            <Button leftSection={<IconSearch size={15} />} loading={searching} onClick={doSearch}>检索</Button>
          </Group>
        }>
          {results === null ? (
            <Text c="dimmed" size="sm" py="xl">输入关键词检索全部报告片段。</Text>
          ) : results.length === 0 ? (
            <Empty title="没有匹配片段" description="换个关键词，或先导入更多资料。" />
          ) : (
            <Stack gap="sm">
              {notice && <Alert color="gray" icon={<IconShieldCheck size={16} />}>{notice}</Alert>}
              {results.map((r) => (
                <Paper key={`${r.document_id}-${r.location}`} withBorder radius="md" p="md">
                  <Group justify="space-between" mb={6}>
                    <Group gap="xs">
                      <IconFileText size={16} />
                      <Text size="sm" fw={600}>{r.source}</Text>
                      <Badge size="xs" variant="light" color="gray">{r.location}</Badge>
                    </Group>
                    <Text size="xs" c="dimmed">相关度 {r.score.toFixed(3)}</Text>
                  </Group>
                  <Text size="sm" lh={1.7}>{r.text}</Text>
                </Paper>
              ))}
            </Stack>
          )}
        </Panel>
        <Panel title="导入资料" subtitle="支持文本、Word、PDF 与 Markdown 片段">
          <Stack gap="sm">
            <Select
              label="归属基金"
              value={p.fundId}
              onChange={(v) => v && p.setFund(v)}
              data={p.workspace.funds.map((f) => ({ value: f.fund_id, label: `${f.manager} · ${f.name}` }))}
            />
            <SegmentedControl
              value={period}
              onChange={setPeriod}
              data={[
                { label: '现期材料', value: 'current' },
                { label: '前期材料', value: 'prior' },
                { label: '参考材料', value: 'reference' },
              ]}
            />
            <FileInput
              label="文件"
              placeholder="选择要导入的报告"
              value={file}
              onChange={setFile}
              leftSection={<IconUpload size={16} />}
            />
            <Button leftSection={<IconUpload size={16} />} loading={uploading} onClick={doUpload}>导入资料</Button>
          </Stack>
        </Panel>
      </div>
      <Panel title="全部资料" className="section-gap">
        <Table.ScrollContainer minWidth={640}>
          <Table highlightOnHover verticalSpacing="md">
            <Table.Thead><Table.Tr><Table.Th>名称</Table.Th><Table.Th>基金</Table.Th><Table.Th>期间</Table.Th><Table.Th>片段</Table.Th><Table.Th>加入时间</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {docs.map((d) => {
                const fund = p.workspace.funds.find((f) => f.fund_id === d.fund_id);
                return (
                  <Table.Tr key={d.id}>
                    <Table.Td><Group gap="xs"><IconFileText size={16} /><Text size="sm" fw={550}>{d.name}</Text></Group></Table.Td>
                    <Table.Td><Text size="sm">{fund ? `${fund.manager} · ${fund.name}` : d.fund_id}</Text></Table.Td>
                    <Table.Td><Badge variant="light" color={d.period === 'current' ? 'teal' : d.period === 'prior' ? 'orange' : 'gray'}>{d.period === 'current' ? '现期' : d.period === 'prior' ? '前期' : '参考'}</Badge></Table.Td>
                    <Table.Td>{d.chunks_count || 0}</Table.Td>
                    <Table.Td><Text size="xs" c="dimmed">{timeText(d.added_at)}</Text></Table.Td>
                    <Table.Td><ActionIcon variant="subtle" onClick={() => p.openDoc(d.id)} aria-label="查看资料"><IconArrowRight size={18} /></ActionIcon></Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Panel>
    </>
  );
}

export function DataPage(p: PageProps) {
  const [kind, setKind] = useState<'funds' | 'nav' | 'holdings'>('nav');
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);

  const kindMeta: Record<string, { title: string; desc: string; columns: string }> = {
    funds: { title: '基金档案', desc: '一次性写入管理人、策略与名称', columns: 'fund_id, name, manager, strategy' },
    nav: { title: '净值序列', desc: '按日期追加到指定基金', columns: 'date, nav（fund_id 由所选基金确定）' },
    holdings: { title: '持仓快照', desc: '按快照日期替换同一天配置', columns: 'asset, weight_pct, as_of' },
  };

  async function doImport() {
    if (!file) { p.notify('请先选择文件', true); return; }
    const mapping: Record<string, string> = {};
    if (kind !== 'funds') mapping.fund_id = p.fundId;
    setImporting(true);
    try {
      const res = await importData(kind, file, mapping) as { imported: number; kind: string };
      p.notify(`已导入 ${res.imported} 条记录`);
      setFile(null);
      await p.refresh();
    } catch (e: any) {
      p.notify(e.message, true);
    } finally {
      setImporting(false);
    }
  }

  return (
    <>
      <PageHeading eyebrow="DATA PIPELINE" title="数据导入" description="把净值、持仓和基金档案接入工作区，作为一切指标与审计的确定性底座。" />
      <MarketData {...p} />
      <SimpleGrid cols={{ base: 1, md: 3 }} className="section-gap">
        <Metric label="基金数" value={p.workspace.funds.length} detail="档案与净值/持仓" icon={<IconDatabase size={18} />} />
        <Metric label="资料数" value={p.workspace.documents.length} detail="报告原文与片段" icon={<IconFileText size={18} />} color="indigo" />
        <Metric label="审计记录" value={p.workspace.runs.length} detail="已保存的尽调" icon={<IconShieldCheck size={18} />} color="orange" />
      </SimpleGrid>
      <div className="grid-2-1 section-gap">
        <Panel title="导入结构化数据" subtitle="CSV / Excel，常见中文列名会自动识别">
          <Stack gap="sm">
            <SegmentedControl value={kind} onChange={(v) => setKind(v as 'funds' | 'nav' | 'holdings')} data={[
              { label: '净值', value: 'nav' },
              { label: '持仓', value: 'holdings' },
              { label: '基金档案', value: 'funds' },
            ]} />
            {kind !== 'funds' && (
              <Select
                label="目标基金"
                value={p.fundId}
                onChange={(v) => v && p.setFund(v)}
                data={p.workspace.funds.map((f) => ({ value: f.fund_id, label: `${f.manager} · ${f.name}` }))}
              />
            )}
            <FileInput
              label="数据文件"
              placeholder="选择 CSV 或 Excel 文件"
              value={file}
              onChange={setFile}
              leftSection={<IconFileImport size={16} />}
            />
            <Button leftSection={<IconDatabase size={16} />} loading={importing} onClick={doImport}>开始导入</Button>
          </Stack>
        </Panel>
        <Panel title="所需列" subtitle={kindMeta[kind].title}>
          <Alert color="gray" icon={<IconDatabase size={16} />} mb="md">{kindMeta[kind].desc}</Alert>
          <Text size="sm" fw={600} mb="xs">文件需包含以下列：</Text>
          <Stack gap="xs">
            {kindMeta[kind].columns.split(', ').map((c) => (
              <Group key={c} gap="xs"><Badge variant="outline" color="teal" style={{ fontFamily: 'monospace' }}>{c}</Badge></Group>
            ))}
          </Stack>
          <Divider my="md" />
          <Text size="xs" c="dimmed">净值与持仓的 fund_id 由所选基金自动补全；基金档案需在文件内提供 fund_id 列。</Text>
        </Panel>
      </div>
    </>
  );
}

export function CopilotPage(p: PageProps) {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<CopilotResponse | null>(null);

  async function send() {
    if (!question.trim()) return;
    setLoading(true);
    try {
      setResp(await askCopilot(question.trim(), p.fundId));
    } catch (e: any) {
      p.notify(e.message, true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <PageHeading eyebrow="RESEARCH COPILOT" title="研究副驾" description="只基于工作区内的报告与已保存审计作答，并给出可定位的原文出处。" />
      <Panel className="section-gap">
        <div className="chat-window">
          {!resp && !loading && (
            <Empty title="提出你的研究问题" description="例如：这位经理的超额收益主要来自哪里？最大回撤发生在什么时期？" />
          )}
          {loading && <Group justify="center" py="xl"><Loader /><Text c="dimmed" size="sm">正在检索与推理…</Text></Group>}
          {resp && (
            <Stack gap="lg">
              <div className="chat-bubble assistant">
                <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{resp.answer}</ReactMarkdown></div>
              </div>
              {resp.steps?.length > 0 && (
                <Paper withBorder radius="md" p="md">
                  <Text size="xs" c="dimmed" fw={600} mb="sm">推理步骤</Text>
                  <Stack gap="xs">
                    {resp.steps.map((s, i) => (
                      <Group key={i} gap="sm" align="flex-start">
                        <ThemeIcon size={24} radius="md" variant="light" color="teal"><IconSparkles size={14} /></ThemeIcon>
                        <div>
                          <Text size="sm" fw={550}>{s.label}</Text>
                          <Text size="xs" c="dimmed">{s.detail}</Text>
                        </div>
                      </Group>
                    ))}
                  </Stack>
                </Paper>
              )}
              {resp.citations?.length > 0 && (
                <div>
                  <Text size="xs" c="dimmed" fw={600} mb="sm">引用出处</Text>
                  <SimpleGrid cols={{ base: 1, md: 2 }}>
                    {resp.citations.map((c, i) => (
                      <Paper key={i} withBorder radius="md" p="sm" className="citation-card">
                        <Group gap="xs" mb={6}><IconFileText size={14} /><Text size="xs" fw={600}>{c.source}</Text><Badge size="xs" variant="light" color="gray">{c.location}</Badge></Group>
                        <Text size="xs" lh={1.6}>{c.text}</Text>
                      </Paper>
                    ))}
                  </SimpleGrid>
                </div>
              )}
              {resp.suggestions?.length > 0 && (
                <Group gap="xs">
                  {resp.suggestions.map((s, i) => (
                    <Badge key={i} size="lg" variant="light" color="teal" className="clickable" onClick={() => setQuestion(s)}>{s}</Badge>
                  ))}
                </Group>
              )}
            </Stack>
          )}
        </div>
        <Group mt="lg" align="flex-end">
          <TextInput
            style={{ flex: 1 }}
            placeholder="基于工作区提问…"
            value={question}
            onChange={(e) => setQuestion(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) send(); }}
          />
          <Button leftSection={<IconSend size={16} />} loading={loading} onClick={send}>提问</Button>
        </Group>
      </Panel>
    </>
  );
}

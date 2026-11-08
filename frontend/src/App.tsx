import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowDownToLine, ArrowLeftRight, ArrowRight, BookOpenText, Check, CheckCheck, ChevronDown,
  CircleHelp, Clock3, FileCheck2, FilePlus2, FileText, FolderClosed, History, ListChecks,
  Languages, LoaderCircle, LockKeyhole, Menu, MessageSquarePlus, PanelRightClose, PenLine, Plus,
  RefreshCw, ScanText, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Undo2,
  Upload, WandSparkles, X,
} from 'lucide-react';
import { api, download, post } from './api';
import { LayoutPreview, ReviewDocument } from './DocumentView';
import { WordProof } from './WordProof';
import { protectionLabels } from './protections';
import { selectionFromEndpoints, selectionSlices } from './textSelection';
import { getLocale, useI18n } from './i18n';
import { createJobPoller } from './jobPolling';
import type { Annotation, Project, ProjectSummary, ProviderConfig, ProviderInfo, Selection } from './types';

type Tab = 'prompt' | 'issues' | 'compare' | 'style' | 'protect' | 'history';
const tabs: { id: Tab; label: string; icon: typeof PenLine }[] = [
  { id: 'prompt', label: '标注', icon: MessageSquarePlus },
  { id: 'issues', label: '检查', icon: ListChecks },
  { id: 'compare', label: '修订', icon: ArrowLeftRight },
  { id: 'style', label: '风格', icon: SlidersHorizontal },
  { id: 'protect', label: '保护', icon: ShieldCheck },
  { id: 'history', label: '历史', icon: History },
];
const statusLabel: Record<string, string> = { pending: '待处理', suggested: '待审阅', applied: '已应用', rejected: '已忽略', conflict: '原文已变更' };
const emptyConfig: ProviderConfig = { provider: 'codex', model: '', base_url: 'https://api.openai.com/v1', api_key_env: 'OPENAI_API_KEY' };
const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试';
const dateLabel = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(getLocale(), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export default function App() {
  const { locale, t } = useI18n();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [tab, setTab] = useState<Tab>('prompt');
  const [view, setView] = useState<'review' | 'layout' | 'proof'>('review');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<string | number>('');
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [config, setConfig] = useState<ProviderConfig>(emptyConfig);
  const [showSettings, setShowSettings] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showGenerate, setShowGenerate] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 720);
  const [filter, setFilter] = useState('open');
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [connected, setConnected] = useState(true);
  const importInput = useRef<HTMLInputElement>(null);
  const tasksInput = useRef<HTMLInputElement>(null);
  const initialProjectId = useRef(new URLSearchParams(window.location.search).get('project'));
  const previousLocale = useRef(locale);
  const active = project?.annotations.find(a => a.id === activeId) || null;
  const working = Boolean(busy || jobId);
  const pending = project?.annotations.filter(a => a.status === 'pending' || a.status === 'suggested') || [];
  const selectedParagraphs = selection && project ? selectionSlices(selection, project.blocks).length : 0;
  const selectedCharacters = selection ? Array.from(selection.quote).length : 0;
  const notify = useCallback((text: string, error = false) => setToast({ text, error }), []);

  const refreshProjects = useCallback(async () => {
    const data = await api<{ projects: ProjectSummary[] }>('/projects');
    setProjects(data.projects);
    setConnected(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let canceled = false;
    void refreshProjects().catch(e => { setConnected(false); notify(message(e), true); });
    void api<{ providers: ProviderInfo[]; config: ProviderConfig }>('/providers', { signal: controller.signal })
      .then(data => { if (!canceled) { setProviders(data.providers); setConfig({ ...emptyConfig, ...data.config }); } })
      .catch(e => { if (!canceled) notify(message(e), true); });
    return () => { canceled = true; controller.abort(); };
  }, [locale, refreshProjects, notify]);

  useEffect(() => {
    if (previousLocale.current === locale) return;
    previousLocale.current = locale;
    const controller = new AbortController();
    let canceled = false;
    if (project) {
      const id = project.id;
      void api<Project>(`/projects/${id}`, { signal: controller.signal })
        .then(updated => { if (!canceled) setProject(previous => previous?.id === id && previous.version <= updated.version ? updated : previous); })
        .catch(error => { if (!canceled) notify(message(error), true); });
    }
    return () => { canceled = true; controller.abort(); };
  }, [locale, project?.id, notify]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), toast.error ? 9000 : 4500);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!project || jobId) return;
    const id = project.id;
    let stopped = false;
    let fetching = false;
    const timer = setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try {
        const updated = await api<Project>(`/projects/${id}`);
        if (!stopped) {
          setProject(previous => previous?.id === id && previous.version < updated.version ? updated : previous);
          setConnected(true);
        }
      } catch { if (!stopped) setConnected(false); }
      finally { fetching = false; }
    }, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [project?.id, jobId, locale]);

  useEffect(() => {
    setSelection(previous => {
      if (!previous) return previous;
      const current = project && selectionFromEndpoints(project.blocks, previous.block_id, previous.start,
        previous.end_block_id || previous.block_id, previous.end);
      return current?.quote === previous.quote ? previous : null;
    });
  }, [project?.version, project?.id]);

  useEffect(() => {
    if (!jobId) return;
    const poller = createJobPoller(jobId, {
      onUpdate(job, updated) {
        setConnected(true);
        setToast(previous => previous?.text === '暂时无法读取任务状态，正在重试。' ? null : previous);
        setJobProgress(job.progress || '正在处理文档…');
        setProject(previous => previous?.id === updated.id && previous.version > updated.version ? previous : updated);
      },
      onFinished(job) {
        setJobId(null);
        setJobProgress('');
        notify(job.status === 'done' ? '已完成，正文和建议已更新' : job.error || 'AI 任务未能完成', job.status === 'error');
        void refreshProjects();
      },
      onInterrupted() {
        setConnected(false);
        setJobProgress('暂时无法读取任务状态，正在重试。');
        notify('暂时无法读取任务状态，正在重试。', true);
      },
      onFatal(error) {
        setJobId(null);
        setJobProgress('');
        notify(message(error), true);
      },
    });
    void poller.poll();
    const timer = setInterval(() => void poller.poll(), 1200);
    return () => { poller.stop(); clearInterval(timer); };
  }, [jobId, locale, notify, refreshProjects]);

  const run = useCallback(async <T,>(label: string, action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(label);
    try { return await action(); }
    catch (e) { notify(message(e), true); return undefined; }
    finally { setBusy(''); }
  }, [notify]);

  const openProject = useCallback(async (id: string) => {
    await run('正在打开文档', async () => {
      const next = await api<Project>(`/projects/${encodeURIComponent(id)}`);
      setProject(next); setSelection(null); setActiveId(null); setView('review'); setNavOpen(false);
      setInstruction('');
    });
  }, [run]);

  useEffect(() => {
    const id = initialProjectId.current;
    initialProjectId.current = null;
    if (id) void openProject(id);
  }, [openProject]);

  useEffect(() => {
    if (!project) return;
    const url = new URL(window.location.href);
    url.searchParams.set('project', project.id);
    window.history.replaceState(window.history.state, '', url);
  }, [project?.id]);

  const mutate = async (path: string, body: unknown = {}, label = '正在保存') => {
    if (!project) return;
    return run(label, async () => {
      const next = await post<Project>(`/projects/${project.id}${path}`, body);
      setProject(next);
      void refreshProjects();
      return next;
    });
  };

  const importDocx = async (file?: File) => {
    if (!file) return;
    await run('正在导入 DOCX', async () => {
      const data = new FormData(); data.append('file', file);
      const next = await api<Project>('/projects/import', { method: 'POST', body: data });
      setProject(next); setSelection(null); setActiveId(null); setView('review'); setNavOpen(false);
      await refreshProjects(); notify('文档已导入，原文件保持不变');
    });
  };

  const selectText = (value: Selection) => {
    setSelection(value); setTab('prompt');
    // On narrow screens the sidebar covers the text and its selection handles.
    if (window.innerWidth > 720) setPanelOpen(true);
  };
  const selectAnnotation = (id: string) => {
    const annotation = project?.annotations.find(a => a.id === id);
    setSelection(null); setActiveId(id); setTab(annotation?.status === 'suggested' ? 'compare' : 'issues'); setPanelOpen(true);
    if (annotation) {
      setView('review');
      requestAnimationFrame(() => document.getElementById(`block-${annotation.block_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    }
  };

  const saveAnnotation = async (suggest: boolean) => {
    if (!selection || !instruction.trim()) return;
    const next = await mutate('/annotations', { ...selection, instruction: instruction.trim() }, '正在保存标注');
    if (!next) return;
    const annotation = next.annotations[next.annotations.length - 1];
    if (!annotation) return;
    setActiveId(annotation.id); setInstruction(''); setSelection(null);
    setTab(suggest ? 'compare' : 'prompt');
    notify(suggest ? '标注已保存' : '标注已保存，可以继续选择下一处');
    if (suggest) await suggestAnnotation(annotation);
  };

  const suggestAnnotation = async (annotation: Annotation) => {
    setActiveId(annotation.id); setTab('compare');
    await mutate(`/annotations/${annotation.id}/suggest`, {}, 'AI 正在生成建议');
  };

  const annotationAction = async (annotation: Annotation, action: 'apply' | 'reject' | 'comment') => {
    const next = await mutate(`/annotations/${annotation.id}/${action}`, {}, action === 'apply' ? '正在写入 Word 修订' : '正在保存');
    if (next) {
      if (action === 'apply') { setSelection(null); notify('已写入 Word 修订，可在历史中撤销'); }
      else if (action === 'comment') notify('已添加正式 Word 批注');
      else notify('已忽略这条建议');
    }
  };

  const startRewrite = async () => {
    if (!project) return;
    await run('正在启动改写', async () => {
      const result = await post<{ job_id: string }>(`/projects/${project.id}/rewrite`, {
        annotation_ids: project.annotations.filter(a => a.status === 'pending').map(a => a.id),
      });
      setJobId(result.job_id); setTab('issues');
    });
  };

  const startGenerate = async (prompt: string, projectId = project?.id) => {
    if (!projectId) return;
    const result = await post<{ job_id: string }>(`/projects/${projectId}/generate`, { prompt });
    setJobId(result.job_id); setView('review'); setShowGenerate(false);
  };

  const downloadFile = async (kind: 'export' | 'tasks') => {
    if (!project) return;
    await run('正在准备下载', () => download(`/projects/${project.id}/${kind}`, `${project.title}${kind === 'export' ? '.docx' : t('-修改任务.json')}`));
  };

  const importTasks = async (file?: File) => {
    if (!file || !project) return;
    await run('正在导入改稿', async () => {
      const body = new FormData(); body.append('file', file);
      const updated = await api<Project>(`/projects/${project.id}/tasks`, { method: 'POST', body });
      setProject(updated); setTab('issues'); notify('改稿已导入，请逐条审阅');
    });
  };

  return <div className={`workspace ${!panelOpen ? 'panel-collapsed' : ''}`}>
    <input ref={importInput} type="file" accept=".docx" className="sr-only" aria-label={t("导入 DOCX 文件")} onChange={e => { void importDocx(e.target.files?.[0]); e.target.value = ''; }} />
    <input ref={tasksInput} type="file" accept=".json,application/json" className="sr-only" aria-label={t("导入 AI 改稿")} onChange={e => { void importTasks(e.target.files?.[0]); e.target.value = ''; }} />
    {navOpen && <button className="drawer-backdrop" aria-label={t("关闭文档列表")} onClick={() => setNavOpen(false)} />}
    <aside className={`project-sidebar ${navOpen ? 'is-open' : ''}`} aria-label={t("本地项目")}>
      <a className="brand" href="#" onClick={e => e.preventDefault()}><span className="brand-symbol"><PenLine size={23} strokeWidth={1.7} /></span><span>{t("文澄")}<small>WENCHENG</small></span></a>
      <div className="sidebar-actions">
        <button className="button primary new-document" onClick={() => setShowNew(true)} disabled={working}><Plus size={17} />{t("新建文档")}</button>
        <button className="button import-button" onClick={() => importInput.current?.click()} disabled={working}><Upload size={15} />{t("导入 DOCX")}</button>
      </div>
      <div className="sidebar-section-label"><span>{t("我的文档")}</span><span>{projects.length}</span></div>
      <nav className="project-list" aria-label={t("文档列表")}>
        {projects.map(item => <button key={item.id} className={`project-link ${project?.id === item.id ? 'active' : ''}`} onClick={() => void openProject(item.id)} disabled={working}>
          <FileText size={17} /><span><strong>{item.title}</strong><small>{dateLabel(item.updated_at)}</small></span>{project?.id === item.id && <span className="current-dot" />}
        </button>)}
        {projects.length === 0 && <div className="sidebar-empty"><FolderClosed size={22} /><p>{t("文档会保存在这里")}</p></div>}
      </nav>
      <div className="sidebar-bottom">
        <button className="settings-link" onClick={() => setShowSettings(true)} disabled={working}><Settings2 size={17} /><span>{t("AI 与本地设置")}</span><span className="provider-pill">{config.provider === 'api' || config.provider === 'openai' ? 'API' : config.provider}</span></button>
        <div className="local-status"><span className={`status-dot ${!connected ? 'offline' : ''}`} />{connected ? t("本地工作空间") : t("本地服务未连接")}<LockKeyhole size={11} /></div>
      </div>
    </aside>

    <main className="main-workspace">
      <header className="topbar">
        <div className="topbar-title"><button className="icon-button mobile-menu" onClick={() => setNavOpen(true)} aria-label={t("打开文档列表")}><Menu size={20} /></button><span className="breadcrumb">{t("工作空间")}</span><span className="breadcrumb-slash">/</span><strong>{project?.title || t("开始一篇好文档")}</strong></div>
        <div className="topbar-actions">
          <LocaleSwitch />
          {project && <><button className="button quiet" onClick={() => setShowGenerate(true)} disabled={working} aria-label={t("继续写作")} title={t("继续写作")}><PenLine size={15} /><span>{t("继续写作")}</span></button><button className="button primary compact" onClick={() => void downloadFile('export')} disabled={working} aria-label={t("导出 DOCX")} title={t("导出 DOCX")}><ArrowDownToLine size={15} /><span>{t("导出 DOCX")}</span></button></>}
          <button className="icon-button panel-toggle" onClick={() => setPanelOpen(v => !v)} aria-label={panelOpen ? t("收起工具栏") : t("展开工具栏")} title={panelOpen ? t("收起工具栏") : t("展开工具栏")}><PanelRightClose size={18} /></button>
        </div>
      </header>

      {(busy || jobId) && <div className="work-progress" role="status"><LoaderCircle size={15} className="spin" /><span>{busy ? t(busy) : typeof jobProgress === 'number' ? t('已完成 {count} 项，正在继续处理…', { count: jobProgress }) : t(jobProgress || 'AI 正在逐段处理…')}</span>{jobId && <small>{t("完成的段落会自动更新")}</small>}</div>}

      {project ? <>
        <div className="document-toolbar">
          <div className="view-tabs" role="tablist" aria-label={t("文档视图")}>
            <button role="tab" aria-selected={view === 'review'} className={view === 'review' ? 'active' : ''} onClick={() => setView('review')}><BookOpenText size={15} />{t("审阅")}</button>
            <button role="tab" aria-selected={view === 'layout'} className={view === 'layout' ? 'active' : ''} onClick={() => setView('layout')}><FileText size={15} />{t("版式预览")}</button>
            <button role="tab" aria-selected={view === 'proof'} className={view === 'proof' ? 'active' : ''} onClick={() => setView('proof')}><FileText size={15} />{t("Word 校样")}</button>
          </div>
          <div className="document-meta"><span>{t('{count} 段', { count: project.blocks.length })}</span><i /><span>{t('{count} 字符', { count: project.blocks.reduce((n, b) => n + Array.from(b.text).length, 0).toLocaleString(locale) })}</span><i /><span>{t('版本 {version}', { version: project.version })}</span></div>
          <button className="button quiet check-button" onClick={() => { setTab('issues'); setPanelOpen(true); void mutate('/analyze', {}, '正在检查重复与套话'); }} disabled={working}><ScanText size={15} />{t("检查表达")}</button>
        </div>
        <div className="document-scroll" key={project.id}>
          {view === 'review' ? <>
            <div className="reading-hint"><span><span className="tiny-line" />{t("可跨段拖选文字，拖动首尾手柄调整范围")}</span><span>{pending.length > 0 ? t('{count} 条待处理标记', { count: pending.length }) : t("克制修改 · 保留原意")}</span></div>
            <ReviewDocument project={project} selection={selection} activeId={activeId} onSelect={selectText} onAnnotation={selectAnnotation} onInvalidSelection={() => { setSelection(null); notify('请从正文文字开始选择，并在正文文字内结束', true); }} />
          </> : view === 'layout' ? <LayoutPreview project={project} onProof={() => setView('proof')} /> : <WordProof key={project.id} project={project} />}
        </div>
        {view === 'review' && selection && !panelOpen && <div className="selection-compose-actions"><span>{t('已选 {count} 字符', { count: selectedCharacters })}{selectedParagraphs > 1 && t(' · 跨 {count} 段', { count: selectedParagraphs })}</span><button className="button primary selection-compose-button" onClick={() => { setTab('prompt'); setPanelOpen(true); }}><MessageSquarePlus size={15} />{t("添加标注")}</button></div>}
        <footer className="document-status"><span><Check size={12} />{t("已保存到本地项目")}</span><span>{t("原文与修改可追溯")}</span></footer>
      </> : <div className="welcome-screen">
        <div className="welcome-heading"><div className="welcome-kicker"><span />{t("为严谨的内容，留出自然的表达")}</div><h1>{t("让文字清楚，")}<br /><em>{t("让修改有据可循。")}</em></h1><p>{t("导入论文或技术文档，选中需要打磨的句子。")}<br />{t("每一处建议，都由你决定。")}</p></div>
        <div className="welcome-actions">
          <button className="start-card" onClick={() => importInput.current?.click()} disabled={working}><span className="start-icon"><Upload size={23} /></span><strong>{t("从已有文档开始")}</strong><p>{t("导入 DOCX，保留批注、公式与引用")}</p><span className="card-link">{t("选择文件")}<ArrowRight size={16} /></span></button>
          <button className="start-card" onClick={() => setShowNew(true)} disabled={working}><span className="start-icon"><FilePlus2 size={23} /></span><strong>{t("从一个想法开始")}</strong><p>{t("写下需求或提纲，逐段生成与审阅")}</p><span className="card-link">{t("新建文档")}<ArrowRight size={16} /></span></button>
        </div>
        <button className="demo-link" disabled={working} onClick={() => void run('正在创建示例', async () => { const result = await post<Project>('/projects/demo'); setProject(result); await refreshProjects(); })}><CircleHelp size={15} />{t("先打开双语示例，熟悉审阅流程")}<ArrowRight size={14} /></button>
        <div className="welcome-principles"><span><ShieldCheck size={16} />{t("原文结构保护")}</span><span><ArrowLeftRight size={16} />{t("逐条对照修订")}</span><span><History size={16} />{t("修改随时回看")}</span></div>
      </div>}
    </main>

    <aside className={`review-sidebar ${panelOpen ? 'is-open' : ''}`} aria-label={t("文档审阅工具")}>
      <div className="review-header"><div><span className="eyebrow">REVIEW DESK</span><h2>{t("审阅工作台")}</h2></div><span className="mode-badge">{t("克制修改")}</span></div>
      <div className="tool-tabs" role="tablist" aria-label={t("审阅工具")}>
        {tabs.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)} className={tab === item.id ? 'active' : ''}><item.icon size={18} strokeWidth={1.65} /><span>{t(item.label)}</span>{item.id === 'issues' && pending.length > 0 && <i>{pending.length}</i>}</button>)}
      </div>
      <div className="tool-panel" role="tabpanel">
        {!project ? <div className="panel-placeholder"><BookOpenText size={32} strokeWidth={1.2} /><h3>{t("先打开一篇文档")}</h3><p>{t("选区提示、表达检查和修改记录")}<br />{t("都会出现在这里。")}</p><div className="workflow-steps"><span><b>01</b>{t("选择文字")}</span><span><b>02</b>{t("写下修改要求")}</span><span><b>03</b>{t("对照并应用修订")}</span></div></div> : <>
          {tab === 'prompt' && <>
            <PanelHeading title={t("精确标注")} description={t("把修改要求留在具体的句子旁。")} />
            {selection ? <div className="selection-card"><div className="selection-label"><span>{t('已选文字 · {count} 字符', { count: selectedCharacters })}{selectedParagraphs > 1 && t(' · 跨 {count} 段', { count: selectedParagraphs })}</span><button className="icon-button small" aria-label={t("清除选区")} onClick={() => setSelection(null)}><X size={13} /></button></div><blockquote>{selection.quote || t("空段落")}</blockquote><p className="helper-text">{t("可跨段拖动首尾手柄；聚焦手柄后用左右方向键微调。")}{selectedParagraphs > 1 && t("这些段落将作为一条标注整体修改。")}</p></div> : <div className="selection-empty"><ScanText size={24} /><p>{t("拖选或长按正文中的文字")}<br /><small>{t("可跨连续多段选择，并拖动首尾手柄微调；点击左侧段号可选整段")}</small></p></div>}
            <label className="field-label" htmlFor="instruction">{t("这段文字需要怎样修改？")}</label>
            <textarea id="instruction" value={instruction} onChange={e => setInstruction(e.target.value)} rows={5} placeholder={t("例如：删除重复说明规则的句子，保留实验依据与引用。")} disabled={!selection || Boolean(busy)} />
            <div className="quick-prompts">{[t("删去重复强调"), t("改善翻译腔"), t("压缩空泛表达")].map(text => <button key={text} disabled={!selection || Boolean(busy)} onClick={() => setInstruction(t('{action}，保留事实、引用和正式文风。', { action: text }))}>{text}</button>)}</div>
            <button className="button primary full" disabled={!selection?.quote || !instruction.trim() || working} onClick={() => void saveAnnotation(true)}><WandSparkles size={16} />{t("保存并生成建议")}</button>
            <button className="button secondary full" disabled={!selection?.quote || !instruction.trim() || Boolean(busy)} onClick={() => void saveAnnotation(false)}><MessageSquarePlus size={15} />{t("仅保存标注")}</button>
            <div className="panel-divider" />
            <div className="subsection-title">{t("交给聊天中的 AI")}</div><p className="helper-text">{t("导出同一组标记，让 skill 按选区处理，再导回建议逐条审阅。")}</p>
            <div className="button-row"><button className="button secondary" disabled={working || !project.annotations.length} onClick={() => void downloadFile('tasks')}><ArrowDownToLine size={14} />{t("导出任务")}</button><button className="button secondary" disabled={working} onClick={() => tasksInput.current?.click()}><Upload size={14} />{t("导入改稿")}</button></div>
          </>}
          {tab === 'issues' && <>
            <PanelHeading title={t("表达检查")} description={t("先定位问题，再决定是否修改。")} />
            <div className="button-row"><button className="button secondary" disabled={working} onClick={() => void mutate('/analyze', {}, '正在检查表达')}><ScanText size={15} />{t("运行检查")}</button><button className="button primary" disabled={working || !project.annotations.some(a => a.status === 'pending')} onClick={() => void startRewrite()}><Sparkles size={14} />{t("生成建议")}</button></div>
            <div className="filter-row"><span>{t('{count} 条标记', { count: project.annotations.length })}</span><label className="select-wrap"><span className="sr-only">{t("筛选标记状态")}</span><select value={filter} onChange={e => setFilter(e.target.value)}><option value="open">{t("待处理")}</option><option value="all">{t("全部标记")}</option><option value="applied">{t("已应用")}</option><option value="rejected">{t("已忽略")}</option><option value="conflict">{t("原文已变更")}</option></select><ChevronDown size={12} /></label></div>
            <div className="issues-list">{project.annotations.filter(a => filter === 'all' || (filter === 'open' ? ['pending', 'suggested', 'conflict'].includes(a.status) : a.status === filter)).map(a => <AnnotationCard key={a.id} annotation={a} active={a.id === activeId} onSelect={() => selectAnnotation(a.id)} onSuggest={() => void suggestAnnotation(a)} onReject={() => void annotationAction(a, 'reject')} disabled={working} />)}</div>
            {!project.annotations.length && <EmptyPanel icon={<ListChecks size={28} />} title={t("还没有标记")} text={t("运行表达检查，或在正文中选择文字添加自己的修改要求。")} />}
          </>}
          {tab === 'compare' && <>
            <PanelHeading title={t("对照修订")} description={t("应用建议后，变更会写为 Word 修订。")} />
            <label className="field-label" htmlFor="review-annotation">{t("选择一条标记")}</label><select id="review-annotation" className="full-select" value={activeId || ''} onChange={e => setActiveId(e.target.value)}><option value="">{t("请选择标记")}</option>{project.annotations.map((a, i) => <option key={a.id} value={a.id}>{i + 1}. {Array.from(a.quote).slice(0, 28).join('')} · {t(statusLabel[a.status])}</option>)}</select>
            {active ? <>
              <div className="compare-instruction"><span className={`status-tag ${active.status}`}>{t(statusLabel[active.status])}</span><p>{active.instruction}</p></div>
              <div className="diff-box original"><span className="diff-label">{t("原文")}</span><p>{active.quote}</p></div>
              {active.replacement !== undefined ? <div className="diff-box replacement"><span className="diff-label">{t("修改建议")}</span><p>{active.replacement || <em>{t("删除所选文字")}</em>}</p></div> : <div className="suggestion-empty"><WandSparkles size={20} /><span>{t("还没有生成建议")}</span></div>}
              {active.reason && <p className="suggestion-reason">{active.reason}</p>}
              {active.status === 'conflict' && <div className="inline-error">{t("这条标记对应的原文已经改变。请重新选择文字并添加标注。")}</div>}
              {active.status === 'suggested' && <button className="button primary full" disabled={working} onClick={() => void annotationAction(active, 'apply')}><CheckCheck size={16} />{t("应用为修订")}</button>}
              {['pending', 'suggested'].includes(active.status) && <><div className="button-row"><button className="button secondary" disabled={working} onClick={() => void suggestAnnotation(active)}><RefreshCw size={14} />{active.replacement !== undefined ? t("重新生成") : t("生成建议")}</button><button className="button secondary" disabled={working} onClick={() => void annotationAction(active, 'reject')}><X size={14} />{t("忽略")}</button></div><button className="button quiet full" disabled={working || active.commented} onClick={() => void annotationAction(active, 'comment')}><MessageSquarePlus size={14} /> {active.commented ? t("已写入 Word 批注") : t("写入 Word 批注")}</button></>}
              {active.status === 'applied' && <div className="success-note"><Check size={15} />{t("已写入文档修订")}</div>}
            </> : <EmptyPanel icon={<ArrowLeftRight size={29} />} title={t("逐条看清每一处改变")} text={t("在检查列表中选择标记，或先为一段文字生成修改建议。")} />}
          </>}
          {tab === 'style' && <StylePanel project={project} disabled={working} onSave={async settings => { await run('正在保存风格', async () => { const next = await api<Project>(`/projects/${project.id}/settings`, { method: 'PATCH', body: JSON.stringify(settings) }); setProject(next); notify('风格设置已保存'); }); }} />}
          {tab === 'protect' && <>
            <PanelHeading title={t("内容保护")} description={t("让表达更自然，同时保留文档的学术信息。")} />
            <div className="protection-banner"><ShieldCheck size={25} /><div><strong>{t("局部修改，保留原文结构")}</strong><p>{t("仅对正文和表格内的文字应用改写。")}</p></div></div>
            <div className="protection-list">{project.protections.map((item, i) => <div key={`${item.kind}-${i}`}><span><LockKeyhole size={15} />{t(protectionLabels[item.kind] || item.kind)}</span><strong>{item.count}</strong></div>)}</div>
            {!project.protections.length && <p className="helper-text">{t("当前文档未识别到需要单独保护的特殊内容。")}</p>}
            <div className="panel-divider" /><div className="subsection-title">{t("保护方式")}</div><ul className="plain-list"><li>{t("公式、域、脚注等特殊内容保留。")}</li><li>{t("遇到受保护范围，提示调整选区。")}</li><li>{t("保留事实、数值、术语与引用关系。")}</li><li>{t("原文变化后，重新核对标记的位置。")}</li></ul>
            <p className="helper-text">{t("审阅视图用于文字定位。需要核对版式时，可切换到版式预览，导出后在 Word 中检查。")}</p>
          </>}
          {tab === 'history' && <>
            <PanelHeading title={t("修改历史")} description={t("每次变更都有记录，可以撤销最近一步。")} />
            <button className="button secondary full" disabled={working || project.history.length === 0} onClick={() => void mutate('/undo', {}, '正在撤销').then(next => { if (next) { setSelection(null); setActiveId(null); notify('已撤销最近一次修改'); } })}><Undo2 size={15} />{t("撤销最近一步")}</button>
            <div className="history-list">{[...project.history].reverse().map((item, i) => <div className="history-item" key={item.id || `${item.version}-${i}`}><span className="history-dot"><Clock3 size={12} /></span><div><strong>{t(item.label)}</strong><span>{dateLabel(item.at)}<i>{t('版本 {version}', { version: item.version })}</i></span></div></div>)}</div>
            {project.history.length === 0 && <EmptyPanel icon={<History size={28} />} title={t("还没有修改记录")} text={t("应用建议、添加批注后，可在这里回看修改。")} />}
          </>}
        </>}
      </div>
      <div className="review-footer"><ShieldCheck size={13} />{t("正文保留论证，处理说明留在侧栏")}</div>
    </aside>

    {toast && <div className={`toast ${toast.error ? 'error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <CircleHelp size={17} /> : <Check size={17} />}<span>{t(toast.text)}</span><button className="icon-button small" onClick={() => setToast(null)} aria-label={t("关闭提示")}><X size={14} /></button></div>}
    {showNew && <CreateDialog disabled={working} onClose={() => setShowNew(false)} onCreate={async (title, prompt) => { await run('正在新建文档', async () => { const next = await post<Project>('/projects', { title, paragraphs: [] }); setProject(next); setSelection(null); setActiveId(null); setView('review'); setShowNew(false); await refreshProjects(); if (prompt.trim()) await startGenerate(prompt, next.id); }); }} />}
    {showGenerate && project && <GenerateDialog disabled={working} onClose={() => setShowGenerate(false)} onGenerate={prompt => void run('正在启动写作', () => startGenerate(prompt))} />}
    {showSettings && <SettingsDialog config={config} providers={providers} disabled={working} onClose={() => setShowSettings(false)} onSave={async next => { await run('正在保存设置', async () => { const result = await api<{ providers?: ProviderInfo[]; config?: ProviderConfig } | ProviderConfig>('/providers', { method: 'PUT', body: JSON.stringify(next) }); setConfig('config' in result && result.config ? { ...emptyConfig, ...result.config } : next); if ('providers' in result && result.providers) setProviders(result.providers); setShowSettings(false); notify('AI 设置已保存'); }); }} />}
  </div>;
}

function LocaleSwitch() {
  const { locale, setLocale, t } = useI18n();
  return <label className="locale-switch"><Languages size={15} aria-hidden="true" /><span className="sr-only">{t('界面语言')}</span><select aria-label={t('界面语言')} value={locale} onChange={event => setLocale(event.target.value === 'en' ? 'en' : 'zh-CN')}><option value="zh-CN">中文</option><option value="en">English</option></select></label>;
}

function PanelHeading({ title, description }: { title: string; description: string }) { return <div className="panel-heading"><h3>{title}</h3><p>{description}</p></div>; }
function EmptyPanel({ icon, title, text }: { icon: ReactNode; title: string; text: string }) { return <div className="empty-panel">{icon}<strong>{title}</strong><p>{text}</p></div>; }

function AnnotationCard({ annotation: a, active, onSelect, onSuggest, onReject, disabled }: { annotation: Annotation; active: boolean; onSelect: () => void; onSuggest: () => void; onReject: () => void; disabled: boolean }) {
  const { t } = useI18n();
  return <div className={`issue-card ${active ? 'active' : ''}`}>
    <button className="issue-body" onClick={onSelect}><div className="issue-meta"><span className="issue-category">{a.category || t("自定义标注")}</span><span className={`status-tag ${a.status}`}>{t(statusLabel[a.status])}</span></div><blockquote>{a.quote}</blockquote><p>{a.instruction}</p></button>
    {a.status === 'pending' && <div className="issue-actions"><button onClick={onSuggest} disabled={disabled}><WandSparkles size={12} />{t("生成建议")}</button><button onClick={onReject} disabled={disabled}>{t("忽略")}</button></div>}
    {a.status === 'suggested' && <div className="issue-actions"><button onClick={onSelect}>{t("查看改稿")}<ArrowRight size={12} /></button></div>}
  </div>;
}

function StylePanel({ project, disabled, onSave }: { project: Project; disabled: boolean; onSave: (settings: Project['settings']) => Promise<void> }) {
  const { t } = useI18n();
  const [rules, setRules] = useState(project.settings.rules || '');
  const [sample, setSample] = useState(project.settings.style_sample || '');
  const [language, setLanguage] = useState(project.settings.language || 'auto');
  useEffect(() => { setRules(project.settings.rules || ''); setSample(project.settings.style_sample || ''); setLanguage(project.settings.language || 'auto'); }, [project.id, project.settings.rules, project.settings.style_sample, project.settings.language]);
  return <>
    <PanelHeading title={t("规则与文风")} description={t("在克制修改的基础上，加入你的写作偏好。")} />
    <div className="style-preset"><PenLine size={17} /><div><strong>{t("正式 · 清楚 · 保留原意")}</strong><p>{t("保留论点、事实、引用与段落结构。")}</p></div></div>
    <label className="field-label" htmlFor="language">{t("文档语言")}</label><select id="language" className="full-select" value={language} onChange={e => setLanguage(e.target.value)}><option value="auto">{t("自动识别中英文")}</option><option value="zh">{t("中文")}</option><option value="en">English</option><option value="mixed">{t("中英混合")}</option></select>
    <label className="field-label" htmlFor="rules">{t("自定义修改规则")}</label><textarea id="rules" value={rules} onChange={e => setRules(e.target.value)} rows={6} placeholder={t("例如：保留技术术语；减少句末重复小结；不把正式文档改成口语。")} />
    <label className="field-label" htmlFor="style-sample">{t("个人文风样本")}<span>{t("可选")}</span></label><textarea id="style-sample" value={sample} onChange={e => setSample(e.target.value)} rows={7} placeholder={t("粘贴一段你认可的文字，AI 会参考它的正式程度、句式与节奏。")} />
    <button className="button primary full" disabled={disabled} onClick={() => void onSave({ rules, style_sample: sample, language })}><Check size={15} />{t("保存风格设置")}</button>
  </>;
}

function Modal({ title, description, children, onClose }: { title: string; description: string; children: ReactNode; onClose: () => void }) {
  const { t } = useI18n();
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const focusables = () => [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') || [])];
    focusables().find(el => ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && !el.closest('.locale-switch'))?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close.current();
      if (event.key === 'Tab') {
        const elements = focusables(); const first = elements[0]; const last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => { document.removeEventListener('keydown', handleKey); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><div ref={dialog} className="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-description" onInvalidCapture={event => {
    const field = event.target;
    if (!(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement)) return;
    field.setCustomValidity('');
    field.setCustomValidity(t(field.validity.valueMissing ? '请填写此项。' : field.validity.typeMismatch ? '请输入有效的网址（包含 https://）。' : field.validity.patternMismatch ? '环境变量名只能包含字母、数字和下划线，且不能以数字开头。' : '请检查输入内容。'));
  }} onInputCapture={event => { const field = event.target; if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) field.setCustomValidity(''); }}><button className="icon-button modal-close" aria-label={t("关闭对话框")} onClick={onClose}><X size={19} /></button><div className="modal-language"><span className="eyebrow">WENCHENG</span><LocaleSwitch /></div><h2 id="dialog-title">{title}</h2><p className="modal-description" id="dialog-description">{description}</p>{children}</div></div>;
}

function CreateDialog({ disabled, onCreate, onClose }: { disabled: boolean; onCreate: (title: string, prompt: string) => Promise<void>; onClose: () => void }) {
  const { t } = useI18n();
  const [title, setTitle] = useState(''); const [prompt, setPrompt] = useState('');
  return <Modal title={t("新建一篇文档")} description={t("从空白开始，或写下要求，让 AI 逐段完成初稿。")} onClose={onClose}><form onSubmit={e => { e.preventDefault(); void onCreate(title.trim(), prompt); }}><label className="field-label" htmlFor="new-title">{t("文档名称")}</label><input id="new-title" value={title} onChange={e => setTitle(e.target.value)} placeholder={t("例如：实验方案与结果分析")} required maxLength={120} /><label className="field-label" htmlFor="new-prompt">{t("写作要求或提纲")}<span>{t("可选")}</span></label><textarea id="new-prompt" value={prompt} onChange={e => setPrompt(e.target.value)} rows={6} placeholder={t("说明主题、读者、结构和现有材料。留空将创建空白文档。")} /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>{t("取消")}</button><button type="submit" className="button primary" disabled={disabled || !title.trim()}>{prompt.trim() ? <Sparkles size={15} /> : <Plus size={15} />}{prompt.trim() ? t("创建并开始写作") : t("创建文档")}</button></div></form></Modal>;
}

function GenerateDialog({ disabled, onGenerate, onClose }: { disabled: boolean; onGenerate: (prompt: string) => void; onClose: () => void }) {
  const { t } = useI18n();
  const [prompt, setPrompt] = useState('');
  return <Modal title={t("继续写作")} description={t("新段落会追加到文档，完成一段即可阅读和标注。")} onClose={onClose}><form onSubmit={e => { e.preventDefault(); onGenerate(prompt.trim()); }}><label className="field-label" htmlFor="generate-prompt">{t("这一部分需要写什么？")}</label><textarea id="generate-prompt" value={prompt} onChange={e => setPrompt(e.target.value)} rows={8} placeholder={t("输入提纲、已有材料、段落数量或写作要求…")} required /><div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>{t("取消")}</button><button type="submit" className="button primary" disabled={disabled || !prompt.trim()}><Sparkles size={15} />{t("开始生成")}</button></div></form></Modal>;
}

function SettingsDialog({ config, providers, disabled, onSave, onClose }: { config: ProviderConfig; providers: ProviderInfo[]; disabled: boolean; onSave: (config: ProviderConfig) => Promise<void>; onClose: () => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState({ ...config });
  const options = providers.length ? providers : [{ id: 'codex', label: 'Codex 本机', available: false }, { id: 'claude', label: 'Claude 本机', available: false }, { id: 'openai', label: 'OpenAI 兼容 API', available: false }];
  const isApi = !['codex', 'claude'].includes(draft.provider);
  const current = options.find(p => p.id === draft.provider);
  return <Modal title={t("AI 与本地设置")} description={t("选择本机代理，或连接你自己的模型 API。")} onClose={onClose}><form onSubmit={(e: FormEvent) => { e.preventDefault(); void onSave(draft); }}><label className="field-label" htmlFor="provider">{t("AI 接入方式")}</label><select id="provider" className="full-select" value={draft.provider} onChange={e => setDraft({ ...draft, provider: e.target.value })}>{options.map(p => <option key={p.id} value={p.id}>{t(p.label)}</option>)}</select><div className="provider-availability"><span className={`status-dot ${current?.available ? '' : 'offline'}`} />{current?.available ? t("已检测到可用配置") : isApi ? t("保存配置后检查对应环境变量") : t("需要在本机安装并登录对应 CLI")}</div><label className="field-label" htmlFor="model">{t("模型名称")}<span>{isApi ? t("必填") : t("可选，留空使用 CLI 默认值")}</span></label><input id="model" value={draft.model || ''} onChange={e => setDraft({ ...draft, model: e.target.value })} placeholder={isApi ? t("填写服务商提供的模型名称") : t("使用本机默认模型")} required={isApi} />{isApi && <><label className="field-label" htmlFor="api-base">API Base URL</label><input id="api-base" type="url" value={draft.base_url || ''} onChange={e => setDraft({ ...draft, base_url: e.target.value })} placeholder="https://api.openai.com/v1" required /><label className="field-label" htmlFor="api-key-env">{t("API Key 环境变量名")}</label><input id="api-key-env" value={draft.api_key_env || ''} onChange={e => setDraft({ ...draft, api_key_env: e.target.value })} placeholder="OPENAI_API_KEY" required pattern="[A-Za-z_][A-Za-z0-9_]*" /><p className="helper-text">{t("在启动本地服务的终端中设置该变量。这里只保存变量名，不保存密钥。")}</p></>}{!isApi && <p className="helper-text">{t("通过本机 CLI 执行独立文档任务。选区、上下文和文风设置会随任务传入。")}</p>}<div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>{t("取消")}</button><button type="submit" className="button primary" disabled={disabled}><Check size={15} />{t("保存设置")}</button></div></form></Modal>;
}

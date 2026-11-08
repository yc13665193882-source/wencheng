import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileImage, LoaderCircle, RefreshCw, Upload } from 'lucide-react';
import { api, download } from './api';
import type { Project } from './types';
import { jumpToProofPage, proofPageSize, proofPageUrl, proofState } from './proof';
import type { ProofMetadata, ProofPage } from './proof';
import { useI18n } from './i18n';

export function WordProof({ project }: { project: Project }) {
  const { locale, t } = useI18n();
  const [proof, setProof] = useState<ProofMetadata | null>(null);
  const [checkedVersion, setCheckedVersion] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const state = proofState(proof, checkedVersion, project.version);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let canceled = false;
    setLoading(true);
    setCheckedVersion(null);
    void api<ProofMetadata>(`/projects/${project.id}/proof`, { signal: controller.signal })
      .then(result => { if (!canceled) { setProof(result); setCheckedVersion(project.version); setError(''); } })
      .catch(reason => { if (!canceled) setError(reason instanceof Error ? reason.message : '无法读取校样'); })
      .finally(() => { if (!canceled) setLoading(false); });
    return () => { canceled = true; controller.abort(); };
  }, [project.id, project.version, refresh]);

  const upload = async (file?: File) => {
    if (!file) return;
    setError('');
    if (!file.name.toLowerCase().endsWith('.pdf')) { setError('请选择从 Word 导出的 PDF 文件。'); return; }
    if (file.size > 50 * 1024 * 1024) { setError('校样 PDF 不能超过 50 MB。'); return; }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await api<ProofMetadata>(`/projects/${project.id}/proof`, { method: 'POST', body: form });
      if (mounted.current) { setCheckedVersion(null); setRefresh(value => value + 1); }
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : '上传校样失败');
    } finally { if (mounted.current) setUploading(false); }
  };
  const exportCurrent = async () => {
    setDownloading(true); setError('');
    try { await download(`/projects/${project.id}/export`, `${project.title}.docx`); }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '下载失败'); }
    finally { if (mounted.current) setDownloading(false); }
  };

  return <div className="word-proof">
    <input ref={input} className="sr-only" type="file" accept=".pdf,application/pdf" aria-label={t('上传 Word 导出的 PDF 校样')} onChange={event => { void upload(event.target.files?.[0]); event.target.value = ''; }} />
    <div className="proof-toolbar">
      <div><strong>{t('Word 校样')}</strong><p>{t('显示本机 Word 导出 PDF 的原始页面；校样用于核对版式，文字修改仍在“审阅”完成。')}</p></div>
      <div className="proof-actions">
        <button className="button secondary compact" disabled={downloading || uploading} onClick={() => void exportCurrent()}>{downloading ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />} {t('下载当前 DOCX')}</button>
        <button className="button primary compact" disabled={uploading} onClick={() => input.current?.click()}>{uploading ? <LoaderCircle size={14} className="spin" /> : <Upload size={14} />}{t(uploading ? '正在处理 PDF…' : proof?.exists ? '更新 PDF 校样' : '上传 PDF 校样')}</button>
      </div>
    </div>
    {error && <div className="inline-error" role="alert">{t(error)} <button className="button quiet compact" onClick={() => { setError(''); setRefresh(value => value + 1); }}>{t('重试读取')}</button></div>}
    {state === 'stale' && <div className="preview-warning proof-stale" role="status"><AlertTriangle size={19} /><div><strong>{t('校样已过期 · 下方为旧版页面')}</strong><p>{t('当前 DOCX 已有修改。请下载当前文档，在 Word 中重新导出 PDF，再更新校样。旧版页码与版式不能代表当前文档。')}</p></div></div>}
    {state === 'checking' && <div className="proof-status checking" role="status"><LoaderCircle size={15} className={loading ? 'spin' : ''} />{t(loading ? '正在检查上传后 DOCX 是否有变化…' : '尚未确认绑定的文档版本，请重试读取。')}{proof?.exists && t(' 下方暂为待核对的已上传页面。')}</div>}
    {state === 'current' && <div className="proof-status current"><CheckCircle2 size={16} />{t('本版本上传的校样')}<span>{t('上传时绑定 · {hash}', { hash: proof!.docx_sha256!.slice(0, 12) })}</span></div>}
    {(state === 'missing' || (!proof?.exists && !loading)) && <div className="proof-empty">
      <FileImage size={35} /><h2>{t('用 Word 的真实分页核对论文')}</h2>
      <ol><li>{t('下载当前 DOCX，在本机 Word 中打开。')}</li><li>{t('使用 Word 的“导出 / 另存为 PDF”，确认修订显示方式。')}</li><li>{t('上传这份 PDF，逐页检查公式、表格、页眉和页码。')}</li></ol>
      <p>{t('支持最多 300 页、50 MB。PDF 页面保留在本地项目，修改 DOCX 后会提示重新导出。')}</p>
    </div>}
    {proof?.exists && <>
      <div className="proof-file-meta"><span title={proof.filename || ''}>{proof.filename} · {t(proof.pages.length === 1 ? '1 页' : '{count} 页', { count: proof.pages.length })}{proof.created_at && ` · ${new Date(proof.created_at).toLocaleString(locale)}`}</span>
        <label>{t('转到')} <select aria-label={t('跳转校样页')} defaultValue="" onChange={event => { jumpToProofPage(document.getElementById(`proof-page-${project.id}-${event.target.value}`)); event.target.value = ''; }}><option value="" disabled>{t('选择页面')}</option>{proof.pages.map(page => <option key={page.number} value={page.number}>{t('第 {number} 页', { number: page.number })}</option>)}</select></label>
      </div>
      <div className={`proof-pages ${state !== 'current' ? 'unverified' : ''}`}>
        {proof.pages.map(page => <ProofPageImage key={`${proof.created_at}-${page.number}`} page={page} proof={proof} projectId={project.id} state={state} />)}
      </div>
    </>}
  </div>;
}

function ProofPageImage({ page, proof, projectId, state }: { page: ProofPage; proof: ProofMetadata; projectId: string; state: string }) {
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  return <figure id={`proof-page-${projectId}-${page.number}`} className="proof-page">
    <figcaption><strong>{t('PDF 第 {number} 页', { number: page.number })}{state === 'stale' ? t(' · 旧版校样') : state !== 'current' ? t(' · 版本待核对') : ''}</strong><span>{proofPageSize(page)}</span></figcaption>
    <div className="proof-page-image" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
      {failed ? <div className="proof-image-error" role="alert">{t('此页图片加载失败')}<button className="button secondary compact" onClick={() => { setFailed(false); setRetry(value => value + 1); }}><RefreshCw size={14} />{t('重试第 {number} 页', { number: page.number })}</button></div>
        : <img src={proofPageUrl(projectId, page.number, proof, retry)} alt={t(state === 'stale' ? 'Word 导出 PDF 第 {number} 页，旧版校样' : 'Word 导出 PDF 第 {number} 页', { number: page.number })} width={page.width} height={page.height} loading="lazy" decoding="async" onError={() => setFailed(true)} />}
    </div>
  </figure>;
}

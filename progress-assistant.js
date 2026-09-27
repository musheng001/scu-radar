(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let draft = null;

  function setState(message, mode='') {
    $('progressState').textContent = message;
    $('progressState').className = `progress-state wide ${mode}`.trim();
  }

  async function api(path, options={}) {
    const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
    const data = await response.json().catch(() => ({error:`服务返回 ${response.status}`}));
    if (!response.ok) throw new Error(data.error || `服务返回 ${response.status}`);
    return data;
  }

  function rows(items, kind) {
    if (!items?.length) return '';
    const label = kind === 'completed' ? '识别为已完成' : kind === 'tasks' ? '识别为下一步' : '补充备注';
    return `<div class="preview-group"><strong>${label}</strong>${items.map(item => {
      const title = typeof item === 'string' ? item : item.title;
      const detail = typeof item === 'string' ? '' : [item.course,item.due_date,item.next_action,item.evidence,item.notes].filter(Boolean).join(' · ');
      return `<div class="preview-row"><b>${esc(title)}</b>${detail ? `<span>${esc(detail)}</span>` : ''}</div>`;
    }).join('')}</div>`;
  }

  function showDraft(data) {
    draft = data;
    $('progressSummary').textContent = data.summary || '已整理本次进展';
    $('progressPreviewBody').innerHTML = rows(data.completed,'completed') + rows(data.tasks,'tasks') + rows(data.notes,'notes');
    $('progressPreview').hidden = false;
    $('saveProgress').disabled = false;
  }

  function renderHistory(entries=[]) {
    $('progressHistory').innerHTML = entries.length ? entries.slice(0,8).map(entry => {
      const count = (entry.completed?.length || 0) + (entry.tasks?.length || 0);
      return `<article class="history-row"><time>${esc(new Date(entry.savedAt).toLocaleString('zh-CN',{hour12:false}))}</time><b>${esc(entry.summary || '学习进展')}</b><span>${count} 个结构化记录 · ${esc(entry.rawInput || '')}</span></article>`;
    }).join('') : '<p class="panel-note">还没有保存过进展。</p>';
  }

  async function refreshStatus() {
    try {
      const data = await api('/api/progress');
      setState(data.gptConfigured ? `GPT 服务已就绪 · ${data.model}` : '本机服务已启动，但尚未设置 OPENAI_API_KEY。', data.gptConfigured ? 'ok' : 'error');
      $('analyzeProgress').disabled = !data.gptConfigured;
      renderHistory(data.entries);
    } catch {
      setState('请从“启动川大雷达.cmd”打开网站；直接双击 HTML 无法调用 GPT。','error');
      $('analyzeProgress').disabled = true;
      renderHistory([]);
    }
  }

  document.querySelectorAll('.ai-progress-trigger').forEach(button => button.addEventListener('click', () => {
    $('progressDialog').showModal();
    refreshStatus();
  }));
  $('closeProgress').addEventListener('click', () => $('progressDialog').close());
  $('clearProgress').addEventListener('click', () => { $('progressForm').reset(); $('progressPreview').hidden = true; draft = null; });
  document.querySelectorAll('[data-progress-example]').forEach(button => button.addEventListener('click', () => {
    const input = $('progressInput');
    input.value = `${input.value.trim()}${input.value.trim() ? '\n' : ''}${button.dataset.progressExample}`;
    input.focus();
  }));
  $('progressForm').addEventListener('submit', async event => {
    event.preventDefault();
    const value = $('progressInput').value.trim();
    if (!value) return;
    $('analyzeProgress').disabled = true;
    $('progressPreview').hidden = true;
    setState('GPT 正在把自然语言整理成可确认的记录……','busy');
    try {
      showDraft(await api('/api/progress/parse',{method:'POST',body:JSON.stringify({text:value})}));
      setState('整理完成。请核对下面内容，再确认写入。','ok');
    } catch (error) {
      setState(`整理失败：${error.message}`,'error');
    } finally {
      $('analyzeProgress').disabled = false;
    }
  });
  $('saveProgress').addEventListener('click', async () => {
    if (!draft) return;
    $('saveProgress').disabled = true;
    setState('正在写入本地进展记录并重建简报……','busy');
    try {
      const result = await api('/api/progress',{method:'POST',body:JSON.stringify({rawInput:$('progressInput').value.trim(),parsed:draft})});
      renderHistory(result.entries);
      $('progressForm').reset(); $('progressPreview').hidden = true; draft = null;
      setState('已写入。重新打开“案头简报”即可看到最新进展。','ok');
    } catch (error) {
      setState(`写入失败：${error.message}`,'error'); $('saveProgress').disabled = false;
    }
  });
})();

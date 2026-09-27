/* Source selector and transparent collection health. No external requests. */
function safeUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : '#'; }
  catch { return '#'; }
}
const sourceSelect = document.createElement('select');
sourceSelect.id = 'sourceSelect';
sourceSelect.setAttribute('aria-label', '按学校或来源筛选');
sourceSelect.style.cssText = 'max-width:100%;padding:10px;margin:0 0 16px;background:var(--paper);color:var(--ink);border:1px solid var(--line)';
sourceSelect.innerHTML = '<option value="">全部学校与来源</option>' + base.sources.map(s => `<option value="${esc(s.id)}">${esc(s.name)} · ${s.count || 0} 条</option>`).join('');
$('cards').before(sourceSelect);
sourceSelect.onchange = () => { sourceFilter = sourceSelect.value; filter = '全部公开信息'; limit = 24; render(); };
renderStatus = function () {
  const sources = base.sources || [];
  const labels = {ok:'文本已采集', warning:'部分待核', error:'采集失败', reachable:'仅入口可达', planned:'待接入', reference:'参考页面'};
  $('sourceMini').innerHTML = sources.map(s => `<button type="button" class="filter" data-source="${esc(s.id)}"><span><i class="dot ${s.status === 'ok' ? 'ok' : 'warn'}"></i>${esc(s.name)}</span><em>${s.count || 0}</em></button>`).join('');
  $('sourceMini').onclick = e => { const b=e.target.closest('[data-source]'); if(b){sourceSelect.value=b.dataset.source;sourceSelect.onchange();if(innerWidth<781)$('rail').classList.remove('open');} };
  $('health').innerHTML = '<div class="notice">下方是采集结果，不代表后台定时任务已启用。附件解析与图片识别可能尚未完成。</div>' + sources.map(s => `<details><summary>${esc(s.name)} · ${labels[s.status] || '待核'}</summary><small>最近尝试：${esc(s.lastAttempt || '未记录')}<br>最近成功：${esc(s.lastSuccess || '尚无')}<br>${esc(s.coverage || '以来源实际采集范围为准')}<br>${(s.errors || []).slice(0,5).map(e => esc(e.error)).join('<br>') || '未记录错误'}</small></details>`).join('');
  $('syncState').textContent='本地数据快照';
  $('syncTime').textContent=base.generatedAt?'构建于 '+new Date(base.generatedAt).toLocaleString('zh-CN',{hour12:false}):'尚未构建';
  $('briefSideMeta').textContent=`${base.items.length} 条公开记录 · ${sources.filter(s=>s.count>0).length} 个有数据来源 · 原文可追溯`;
};
renderStatus();
render();
const channelPanel = document.createElement('section');
channelPanel.className = 'panel';
channelPanel.innerHTML = '<h2>登录入口与公众号</h2><div class="official">' + (base.channels?.loginEntrances || []).map(x => `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${esc(x.name)} · 手动登录 ↗</a>`).join('') + '</div><details><summary>公众号清单 · 尚未自动订阅</summary>' + (base.channels?.wechatAccounts || []).map(x => `<p>${esc(x.name)}<br><small>${esc(x.evidence ? '已有官网名称依据；文章接入待完成' : '身份与访问待核验')}</small></p>`).join('') + '</details>';
$('health').parentElement.after(channelPanel);
const briefPanel = document.createElement('section');
briefPanel.className = 'panel';
briefPanel.innerHTML = '<h2>秘书简报</h2><div class="official"><a href="secretary-brief.md" target="_blank" rel="noopener noreferrer">打开今日秘书简报 ↗</a><a href="secretary-brief.json" target="_blank" rel="noopener noreferrer">查看机器版 JSON ↗</a></div><small>由本地雷达构建；不保存邮箱令牌，不自动发送邮件。</small>';
channelPanel.after(briefPanel);
const categoryClick = $('filters').onclick;
$('filters').onclick = e => {if(e.target.closest('[data-filter]')){sourceFilter='';sourceSelect.value='';} categoryClick(e);};

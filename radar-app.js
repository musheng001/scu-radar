(() => {
  'use strict';
  const base = window.SCU_RADAR_DATA || {generatedAt:null,items:[],sources:[],summary:{},channels:{}};
  const channelCatalog = window.SCU_CHANNEL_CATALOG || {groups:{},total:0,errors:[]};
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const safeUrl = value => { try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : '#'; } catch { return '#'; } };
  const PERSONAL_KEY = 'scu-radar-personal-v2';
  const THEME_KEY = 'scu-radar-theme-v2';
  const filters = ['案头优先','全部公开信息','竞赛','讲座会议','校园活动','教务规则','交流项目','招募实践','学院动态','已收藏'];
  let personal = [];
  let filter = '案头优先';
  let sourceFilter = '';
  let limit = 18;
  let cloudProfile = null;
  try { const stored = JSON.parse(localStorage.getItem(PERSONAL_KEY) || '[]'); personal = Array.isArray(stored) ? stored : []; } catch {}

  const dateKey = value => value ? new Date(value).getTime() || 0 : 0;
  const daysUntil = value => value ? Math.ceil((new Date(value + 'T23:59:59+08:00') - Date.now()) / 86400000) : Infinity;
  const formatDate = value => { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.getTime()) ? `${date.getMonth()+1}月${date.getDate()}日` : '日期待核'; };
  const savePersonal = () => {
    localStorage.setItem(PERSONAL_KEY, JSON.stringify(personal));
    if (window.RadarCloud?.status().configured) {
      window.RadarCloud.savePersonal(personal).then(() => setCloudState('云端已同步','ok')).catch(error => setCloudState(`云同步失败：${error.message}`,'error'));
    }
  };
  const normalizedTitle = value => String(value || '').replace(/[\s—–·•“”‘’《》【】（）()：:，,。.!！?？]/g,'').toLowerCase();

  function allItems() {
    const manual = personal.filter(item => !item.savedRef).map(item => ({
      ...item, manual:true, score:item.score || 55,
      publishedAt:item.publishedAt || new Date(item.created).toISOString(),
      state:item.deadline && daysUntil(item.deadline) < 0 ? 'closed' : 'review'
    }));
    return [...manual, ...(base.items || [])]
      .map(item => ({...item, saved:personal.some(record => record.savedRef === item.id) || item.saved}))
      .filter((item,index,array) => array.findIndex(other => (other.url && other.url === item.url) || other.id === item.id) === index);
  }

  function visibleDedupe(items) {
    const seen = new Set();
    return items.filter(item => {
      const day = String(item.publishedAt || '').slice(0,10);
      const key = normalizedTitle(item.title) + '|' + day;
      if (!normalizedTitle(item.title) || !seen.has(key)) { seen.add(key); return true; }
      return false;
    });
  }

  function relevant(item) {
    if (filter === '案头优先') return item.state === 'active' || item.state === 'review';
    if (filter === '全部公开信息') return true;
    if (filter === '已收藏') return item.saved;
    return item.category === filter;
  }

  function sorted(items) {
    const mode = $('sort').value;
    return [...items].sort((a,b) => {
      if (mode === 'newest') return dateKey(b.publishedAt) - dateKey(a.publishedAt);
      if (mode === 'deadline') return (a.deadline || '9999').localeCompare(b.deadline || '9999') || dateKey(b.publishedAt) - dateKey(a.publishedAt);
      return (b.score || 0) - (a.score || 0) || dateKey(b.publishedAt) - dateKey(a.publishedAt);
    });
  }

  function cardHtml(item) {
    const published = item.publishedAt ? new Date(item.publishedAt) : null;
    const validDate = published && !Number.isNaN(published.getTime());
    const day = validDate ? String(published.getDate()).padStart(2,'0') : '—';
    const month = validDate ? `${published.getMonth()+1}月` : '待核';
    const remaining = daysUntil(item.deadline);
    let stateTag = '';
    if (item.deadline) {
      const label = remaining < 0 ? '已截止' : remaining === 0 ? '今日截止' : remaining <= 14 ? `${remaining}天后截止` : `截止 ${formatDate(item.deadline)}`;
      stateTag = `<span class="tag ${remaining < 0 ? 'closed' : 'deadline'}">${label}</span>`;
    } else if (item.state === 'review') stateTag = '<span class="tag attention">待核</span>';
    const parse = item.parseStatus === 'api_metadata' ? '<span class="tag machine">目录线索</span>' : item.parseStatus === 'list_only' ? '<span class="tag machine">仅列表</span>' : '';
    return `<article class="card" data-card="${esc(item.id)}">
      <div class="date"><b>${day}</b><span>${month}</span></div>
      <div>
        <div class="meta"><span class="tag">${esc(item.category || '未分类')}</span>${stateTag}${parse}<span>${esc(item.sourceName || item.organizer || '公开来源')}</span></div>
        <h3>${esc(item.title)}</h3>
        <p class="summary">${esc(item.summary || '暂无摘要，请核对官方原文。')}</p>
        <div class="card-actions">
          <a href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">核对原文 ↗</a>
          <button type="button" data-expand="${esc(item.id)}">展开摘要</button>
          <button type="button" data-save="${esc(item.id)}">${item.saved ? '★ 已收藏' : '☆ 收藏'}</button>
          ${item.manual ? `<button type="button" data-delete="${esc(item.id)}">删除补录</button>` : ''}
          <span class="score">相关度 ${Math.round(item.score || 0)}</span>
        </div>
      </div>
    </article>`;
  }

  function renderNavigation(items) {
    const saved = items.filter(item => item.saved).length;
    $('filters').innerHTML = filters.map(name => {
      const count = name === '案头优先' ? items.filter(item => item.state === 'active' || item.state === 'review').length
        : name === '全部公开信息' ? items.length : name === '已收藏' ? saved : items.filter(item => item.category === name).length;
      return `<button type="button" class="nav-button ${name === filter ? 'active' : ''}" data-filter="${esc(name)}"><span>${esc(name)}</span><em>${count}</em></button>`;
    }).join('');
    $('sourceSelect').innerHTML = '<option value="">全部来源</option>' + (base.sources || []).map(source => `<option value="${esc(source.id)}">${esc(source.name)} · ${source.count || 0}</option>`).join('');
    $('sourceSelect').value = sourceFilter;
  }

  function renderMetrics(items) {
    const review = items.filter(item => item.state === 'active' || item.state === 'review').length;
    const recent = items.filter(item => { const key = dateKey(item.publishedAt); return key <= Date.now() && Date.now() - key < 14 * 864e5; }).length;
    const liveSources = (base.sources || []).filter(source => source.count > 0).length;
    $('stats').innerHTML = [[review,'值得核对'],[recent,'近14日新增'],[liveSources,'有数据来源'],[base.summary?.totalArticles || items.length,'公开条目']]
      .map(([value,label]) => `<div class="metric"><b>${value}</b><span>${label}</span></div>`).join('');
    $('headline').textContent = review ? `${review} 条事项，先判断值不值得投入。` : '今天没有必须立刻投入的事项。';
    $('briefText').textContent = '首页只保留行动判断、检索与原文。来源诊断、公众号和登录入口已经收进侧栏，不再挤占主视野。';
  }

  function renderDesk(items) {
    const candidates = sorted(items.filter(item => item.state === 'active' || item.state === 'review')).slice(0,5);
    $('actionList').innerHTML = candidates.length ? candidates.map(item => `<div class="action-item"><a href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a><small>${item.deadline ? formatDate(item.deadline) : '截止日待核'} · ${esc(item.sourceName || item.organizer || '公开来源')}</small></div>`).join('') : '<div class="action-item"><small>暂无待处理事项。</small></div>';
    const sources = base.sources || [];
    const ok = sources.filter(source => source.status === 'ok').length;
    const warning = sources.filter(source => source.status === 'warning').length;
    const error = sources.filter(source => source.status === 'error').length;
    $('healthSummary').innerHTML = [[ok,'正常'],[warning,'待核'],[error,'失败']].map(([value,label]) => `<div class="health-chip"><b>${value}</b><span>${label}</span></div>`).join('');
    $('sourceList').innerHTML = sources.map(source => `<div class="source-row"><div><strong>${esc(source.name)}</strong><small>${esc(source.coverage || (source.errors || []).map(errorItem => errorItem.error).slice(0,2).join('；') || '以当前缓存为准')}</small></div><span class="status ${esc(source.status || 'warning')}">${source.status === 'ok' ? '正常' : source.status === 'error' ? '失败' : '待核'} · ${source.count || 0}</span></div>`).join('');
  }

  function renderChannels(query='') {
    const needle = query.trim().toLowerCase();
    const groups = Object.entries(channelCatalog.groups || {}).map(([name,rows]) => {
      const visible = rows.filter(row => !needle || `${row.name} ${row.kind} ${row.url}`.toLowerCase().includes(needle));
      if (!visible.length) return '';
      const links = visible.map(row => `<a class="channel-link" href="${esc(safeUrl(row.url))}" target="_blank" rel="noopener noreferrer"><span>${esc(row.name)}</span><small>${row.access === 'login' ? '需登录' : row.access === 'blocked-check' ? '访问校验' : row.access === 'public' ? '公开' : '公开或登录'} · ${esc(new URL(row.url).hostname)}</small></a>`).join('');
      return `<section class="channel-group"><h3>${esc(name)} · ${visible.length}</h3><div class="channel-grid">${links}</div></section>`;
    }).join('');
    $('channelList').innerHTML = groups || '<div class="empty">没有匹配的渠道。</div>';
    $('channelMeta').textContent = `${channelCatalog.total || 0} 个官方渠道 · ${channelCatalog.generatedAt ? new Date(channelCatalog.generatedAt).toLocaleString('zh-CN',{hour12:false}) : '等待目录刷新'} · 目录收录不等于已经抓取正文`;
  }

  function render() {
    const items = allItems();
    const query = $('query').value.trim().toLowerCase();
    const filtered = items.filter(item => !sourceFilter || item.sourceId === sourceFilter)
      .filter(item => query ? true : relevant(item))
      .filter(item => [item.title,item.summary,item.organizer,item.sourceName,item.rawCategory].join(' ').toLowerCase().includes(query));
    const list = visibleDedupe(sorted(filtered));
    renderNavigation(items);
    renderMetrics(items);
    renderDesk(items);
    $('feedTitle').textContent = query ? `检索：${$('query').value.trim()}` : filter;
    $('count').textContent = `${list.length} 条${list.length < filtered.length ? ` · 合并 ${filtered.length-list.length} 条重复` : ''}`;
    $('cards').innerHTML = list.length ? list.slice(0,limit).map(cardHtml).join('') : '<div class="empty">当前视图没有信息。换一个分类或清空检索词即可。</div>';
    $('more').hidden = list.length <= limit;
  }

  function setCloudState(message, kind='') {
    const node = $('cloudState');
    if (node) { node.textContent = message; node.className = `cloud-state ${kind}`.trim(); }
  }

  function mergePersonal(remote, local) {
    const merged = new Map();
    [...(remote || []),...(local || [])].forEach(item => merged.set(item.savedRef ? `saved:${item.savedRef}` : `item:${item.id}`, item));
    return [...merged.values()];
  }

  function fillProfile(profile) {
    const form = $('profileForm');
    if (!form) return;
    form.elements.display_name.value = profile?.display_name || '';
    form.elements.target_schools.value = (profile?.target_schools || []).join('，');
    form.elements.interests.value = (profile?.interests || []).join('，');
    form.elements.notes.value = profile?.notes || '';
  }

  async function initCloud() {
    if (!window.RadarCloud) return setCloudState('云端模块未加载，当前使用本地离线模式','error');
    try {
      const result = await window.RadarCloud.init();
      if (result.mode === 'local') {
        setCloudState('本地离线模式：填写 Supabase 配置后会自动迁移收藏和补录');
        return;
      }
      if (result.mode === 'cloud-signed-out') {
        setCloudState('Supabase 已配置；绑定邮箱后启用个人云空间');
        return;
      }
      personal = mergePersonal(result.personal, personal);
      cloudProfile = result.profile || {};
      localStorage.setItem(PERSONAL_KEY, JSON.stringify(personal));
      fillProfile(cloudProfile);
      await window.RadarCloud.savePersonal(personal);
      setCloudState(result.user?.is_anonymous ? '云端已同步 · 当前为匿名账户，建议绑定邮箱' : '云端已同步 · 可跨设备恢复','ok');
      $('syncState').textContent = '公开数据与个人云端已就绪';
      render();
    } catch (error) {
      setCloudState(`云端不可用，已自动留在本地模式：${error.message}`,'error');
    }
  }

  function setTheme(theme) {
    if (!['ink','night','minimal'].includes(theme)) return;
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
    document.querySelectorAll('[data-theme-choice]').forEach(button => button.classList.toggle('active', button.dataset.themeChoice === theme));
  }
  window.setRadarTheme = setTheme;

  const requestedTheme = new URLSearchParams(location.search).get('theme');
  const initialTheme = ['ink','night','minimal'].includes(requestedTheme) ? requestedTheme : (localStorage.getItem(THEME_KEY) || 'ink');
  setTheme(initialTheme);
  $('today').textContent = new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'short'}).format(new Date());
  const generated = base.generatedAt ? new Date(base.generatedAt) : null;
  $('syncState').textContent = generated ? '本地快照已就绪' : '尚未构建';
  $('syncTime').textContent = generated ? generated.toLocaleString('zh-CN',{hour12:false}) : '请运行更新器';

  $('filters').addEventListener('click', event => { const button = event.target.closest('[data-filter]'); if (!button) return; filter = button.dataset.filter; sourceFilter = ''; limit = 18; render(); if (innerWidth < 781) $('rail').classList.remove('open'); });
  $('sourceSelect').addEventListener('change', event => { sourceFilter = event.target.value; filter = '全部公开信息'; limit = 18; render(); });
  $('query').addEventListener('input', () => { limit = 18; render(); });
  $('sort').addEventListener('change', render);
  $('more').addEventListener('click', () => { limit += 24; render(); });
  $('menu').addEventListener('click', () => $('rail').classList.toggle('open'));
  document.querySelectorAll('[data-theme-choice]').forEach(button => button.addEventListener('click', () => setTheme(button.dataset.themeChoice)));

  $('cards').addEventListener('click', event => {
    const expand = event.target.closest('[data-expand]');
    const save = event.target.closest('[data-save]');
    const remove = event.target.closest('[data-delete]');
    if (expand) {
      const card = expand.closest('.card'); card.classList.toggle('expanded');
      expand.textContent = card.classList.contains('expanded') ? '收起摘要' : '展开摘要';
    }
    if (save) {
      const id = save.dataset.save;
      const own = personal.find(item => item.id === id);
      if (own) own.saved = !own.saved;
      else { const ref = personal.find(item => item.savedRef === id); if (ref) personal = personal.filter(item => item !== ref); else personal.push({id:crypto.randomUUID(),savedRef:id,created:Date.now()}); }
      savePersonal(); render();
    }
    if (remove && confirm('删除这条人工补录？')) { personal = personal.filter(item => item.id !== remove.dataset.delete); savePersonal(); render(); }
  });

  $('openSources').addEventListener('click', () => $('sourceDialog').showModal());
  $('openSourcesSecondary').addEventListener('click', () => $('sourceDialog').showModal());
  $('closeSources').addEventListener('click', () => $('sourceDialog').close());
  $('openChannels').addEventListener('click', () => { renderChannels($('channelQuery').value); $('channelDialog').showModal(); });
  $('closeChannels').addEventListener('click', () => $('channelDialog').close());
  $('channelQuery').addEventListener('input', event => renderChannels(event.target.value));
  $('add').addEventListener('click', () => $('entryDialog').showModal());
  $('account').addEventListener('click', () => $('accountDialog').showModal());
  $('closeAccount').addEventListener('click', () => $('accountDialog').close());
  $('cancel').addEventListener('click', () => $('entryDialog').close());
  $('cancelSecondary').addEventListener('click', () => $('entryDialog').close());
  $('entry').addEventListener('submit', event => {
    event.preventDefault();
    const data = new FormData(event.target), url = String(data.get('url'));
    if (!/^https?:\/\//i.test(url)) return alert('请输入 http 或 https 官方来源链接');
    personal.unshift({id:'manual-'+crypto.randomUUID(),title:String(data.get('title')).trim(),category:String(data.get('category')),organizer:String(data.get('organizer')).trim(),deadline:String(data.get('deadline')),url,summary:String(data.get('summary')).trim(),created:Date.now(),state:'review',score:70,saved:false});
    savePersonal(); event.target.reset(); $('entryDialog').close(); render();
  });
  $('profileForm').addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(event.target);
    cloudProfile = {
      display_name:String(data.get('display_name') || '').trim(),
      target_schools:String(data.get('target_schools') || '').split(/[，,]/).map(value => value.trim()).filter(Boolean),
      interests:String(data.get('interests') || '').split(/[，,]/).map(value => value.trim()).filter(Boolean),
      notes:String(data.get('notes') || '').trim()
    };
    try { await window.RadarCloud.saveProfile(cloudProfile); setCloudState('个人资料已保存到云端','ok'); }
    catch (error) { setCloudState(`保存失败：${error.message}`,'error'); }
  });
  $('emailForm').addEventListener('submit', async event => {
    event.preventDefault();
    const email = String(new FormData(event.target).get('email') || '').trim();
    try { await window.RadarCloud.sendMagicLink(email); setCloudState('验证邮件已发送，请在同一浏览器完成确认','ok'); }
    catch (error) { setCloudState(`邮件发送失败：${error.message}`,'error'); }
  });
  $('export').addEventListener('click', () => { const blob = new Blob([JSON.stringify(personal,null,2)],{type:'application/json'}), link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'scu-radar-personal.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href),1000); });
  $('import').addEventListener('click', () => $('file').click());
  $('file').addEventListener('change', async event => { try { const data = JSON.parse(await event.target.files[0].text()); if (!Array.isArray(data)) throw Error('不是数组'); if (confirm(`导入 ${data.length} 条个人数据并替换当前内容？`)) { personal = data; savePersonal(); render(); } } catch (error) { alert('导入失败：'+error.message); } event.target.value=''; });
  render();
  initCloud();
})();

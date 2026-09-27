(() => {
  'use strict';
  const config = window.SCU_RADAR_SUPABASE || {};
  const configured = /^https:\/\/.+\.supabase\.co\/?$/i.test(config.url || '') && Boolean(config.publishableKey);
  let client = null;
  let user = null;

  const loadSdk = () => new Promise((resolve, reject) => {
    if (window.supabase?.createClient) return resolve();
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
    script.async = true;
    script.onload = resolve;
    script.onerror = () => reject(new Error('Supabase SDK 加载失败'));
    document.head.appendChild(script);
  });

  async function ensureSession() {
    const {data:{session}} = await client.auth.getSession();
    if (session?.user) return session.user;
    if (!config.anonymousSignIn) return null;
    const {data,error} = await client.auth.signInAnonymously();
    if (error) throw error;
    return data.user;
  }

  async function init() {
    if (!configured) return {mode:'local', reason:'Supabase 尚未配置'};
    await loadSdk();
    client = window.supabase.createClient(config.url.replace(/\/$/,''), config.publishableKey, {
      auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}
    });
    user = await ensureSession();
    if (!user) return {mode:'cloud-signed-out'};
    const personal = await loadPersonal();
    const profile = await loadProfile();
    return {mode:'cloud', user, personal, profile};
  }

  async function loadPersonal() {
    if (!client || !user) return [];
    const [bookmarkResult, submissionResult] = await Promise.all([
      client.from('bookmarks').select('item_id,created_at').eq('user_id', user.id),
      client.from('submissions').select('id,title,category,organizer,deadline,url,summary,state,score,created_at').eq('user_id', user.id).order('created_at',{ascending:false})
    ]);
    if (bookmarkResult.error) throw bookmarkResult.error;
    if (submissionResult.error) throw submissionResult.error;
    const bookmarks = (bookmarkResult.data || []).map(row => ({id:`bookmark-${row.item_id}`,savedRef:row.item_id,created:new Date(row.created_at).getTime()}));
    const submissions = (submissionResult.data || []).map(row => ({
      id:row.id,title:row.title,category:row.category,organizer:row.organizer,deadline:row.deadline || '',url:row.url,
      summary:row.summary || '',state:row.state || 'review',score:row.score || 70,created:new Date(row.created_at).getTime(),saved:false
    }));
    return [...submissions,...bookmarks];
  }

  async function savePersonal(personal) {
    if (!client || !user) return {mode:'local'};
    const bookmarks = personal.filter(item => item.savedRef).map(item => ({user_id:user.id,item_id:item.savedRef}));
    const submissions = personal.filter(item => !item.savedRef).map(item => ({
      user_id:user.id,id:item.id,title:item.title,category:item.category,organizer:item.organizer,deadline:item.deadline || null,
      url:item.url,summary:item.summary || '',state:item.state || 'review',score:item.score || 70
    }));
    const keepBookmarkIds = new Set(bookmarks.map(row => row.item_id));
    const keepSubmissionIds = new Set(submissions.map(row => row.id));
    const [remoteBookmarks,remoteSubmissions] = await Promise.all([
      client.from('bookmarks').select('item_id').eq('user_id',user.id),
      client.from('submissions').select('id').eq('user_id',user.id)
    ]);
    if (remoteBookmarks.error) throw remoteBookmarks.error;
    if (remoteSubmissions.error) throw remoteSubmissions.error;
    if (bookmarks.length) {
      const {error} = await client.from('bookmarks').upsert(bookmarks,{onConflict:'user_id,item_id'});
      if (error) throw error;
    }
    const staleBookmarks = (remoteBookmarks.data || []).map(row => row.item_id).filter(id => !keepBookmarkIds.has(id));
    if (staleBookmarks.length) {
      const {error} = await client.from('bookmarks').delete().eq('user_id',user.id).in('item_id',staleBookmarks);
      if (error) throw error;
    }
    if (submissions.length) {
      const {error} = await client.from('submissions').upsert(submissions,{onConflict:'user_id,id'});
      if (error) throw error;
    }
    const staleSubmissions = (remoteSubmissions.data || []).map(row => row.id).filter(id => !keepSubmissionIds.has(id));
    if (staleSubmissions.length) {
      const {error} = await client.from('submissions').delete().eq('user_id',user.id).in('id',staleSubmissions);
      if (error) throw error;
    }
    return {mode:'cloud'};
  }

  async function loadProfile() {
    if (!client || !user) return null;
    const {data,error} = await client.from('profiles').select('display_name,target_schools,interests,notes').eq('user_id',user.id).maybeSingle();
    if (error) throw error;
    return data;
  }

  async function saveProfile(profile) {
    if (!client || !user) throw new Error('云端尚未连接');
    const {error} = await client.from('profiles').upsert({user_id:user.id,...profile},{onConflict:'user_id'});
    if (error) throw error;
  }

  async function sendMagicLink(email) {
    if (!client) throw new Error('请先配置 Supabase');
    const response = user?.is_anonymous
      ? await client.auth.updateUser({email})
      : await client.auth.signInWithOtp({email,options:{emailRedirectTo:location.href.split('#')[0]}});
    const {error} = response;
    if (error) throw error;
  }

  function status() {
    return {configured,mode:client ? (user ? 'cloud' : 'cloud-signed-out') : 'local',user};
  }

  window.RadarCloud = {init,loadPersonal,savePersonal,loadProfile,saveProfile,sendMagicLink,status};
})();

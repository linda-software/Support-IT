/* Plataforma de Infraestructura v22 · shell de sesión y permisos */
(function(){
  const roleName={standard:'Usuario estándar',admin:'Admin',superadmin:'Superadmin'};
  async function boot(){
    try{
      const r=await fetch('/api/me',{headers:{'Accept':'application/json'}});
      if(r.status===401){ location.href='/login'; return; }
      if(!r.ok) return;
      const data=await r.json(),u=data.user,p=data.permissions||{};
      window.INFRA_USER=u; window.INFRA_PERMISSIONS=p;
      if(u.must_change_password && location.pathname!='/cambiar-contrasena' && location.pathname!='/perfil'){ location.href='/cambiar-contrasena'; return; }
      document.documentElement.dataset.role=u.role;
      document.querySelectorAll('[data-role-only]').forEach(el=>{
        const allowed=el.dataset.roleOnly.split(',').map(x=>x.trim());
        if(!allowed.includes(u.role)) el.style.display='none';
      });
      document.querySelectorAll('[data-permission]').forEach(el=>{
        if(!p[el.dataset.permission]) el.style.display='none';
      });
      if(!document.getElementById('infra-user-pill')){
        const pill=document.createElement('div');pill.id='infra-user-pill';pill.innerHTML=`<div class="infra-user-dot"></div><div class="infra-user-info" title="Abrir Mi perfil"><b>${esc(u.display_name)}</b><span>${esc(roleName[u.role]||u.role)}</span></div><button class="infra-profile-btn" title="Mi perfil" aria-label="Mi perfil">☺</button><button class="infra-logout-btn" title="Cerrar sesión" aria-label="Cerrar sesión">↪</button>`;
        pill.querySelector('.infra-user-info').onclick=()=>location.href='/perfil';
        pill.querySelector('.infra-profile-btn').onclick=()=>location.href='/perfil';
        pill.querySelector('.infra-logout-btn').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST'});location.href='/login'};
        document.body.appendChild(pill);
        const style=document.createElement('style');style.textContent=`#infra-user-pill{position:fixed;right:16px;bottom:16px;z-index:99999;display:flex;align-items:center;gap:9px;padding:9px 10px 9px 12px;border:1px solid rgba(148,163,184,.28);border-radius:14px;background:rgba(255,255,255,.94);backdrop-filter:blur(16px);box-shadow:0 14px 40px rgba(15,23,42,.13);font-family:Inter,Segoe UI,system-ui,sans-serif;color:#172033}#infra-user-pill>div:nth-child(2){display:grid;line-height:1.15;cursor:pointer}#infra-user-pill b{font-size:11.5px;max-width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#infra-user-pill span{font-size:10px;color:#667085;margin-top:3px}.infra-user-dot{width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px #dcfce7}#infra-user-pill button{border:0;background:#f1f5f9;color:#475569;width:28px;height:28px;border-radius:9px;cursor:pointer;font-weight:800} @media(max-width:600px){#infra-user-pill{right:10px;bottom:10px}#infra-user-pill>div:nth-child(2){display:none}}`;document.head.appendChild(style);
      }
      document.dispatchEvent(new CustomEvent('infra:user-ready',{detail:data}));
    }catch(e){console.warn('No se pudo cargar sesión',e)}
  }
  function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();

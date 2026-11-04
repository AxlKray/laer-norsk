const C='laer-norsk-v37';
const ASSETS=['./','./index.html','./manifest.json','./icon-192.png','./icon-512.png','./apple-touch-icon.png'];
self.addEventListener('install',e=>{ e.waitUntil(caches.open(C).then(c=>c.addAll(ASSETS))); self.skipWaiting() });
self.addEventListener('activate',e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())) });
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  const url=new URL(e.request.url);
  const isPage=e.request.mode==='navigate'||url.pathname.endsWith('/')||url.pathname.endsWith('index.html');
  if(isPage){
    // Seite: immer zuerst online die neueste Version holen, offline die gespeicherte nehmen
    e.respondWith(fetch(e.request,{cache:'no-store'}).then(res=>{ if(res.ok){ const cp=res.clone(); caches.open(C).then(c=>c.put('./index.html',cp)) } return res })
      .catch(()=>caches.match('./index.html').then(r=>r||caches.match('./'))));
    return;
  }
  e.respondWith(caches.match(e.request,{ignoreSearch:true}).then(hit=>hit||fetch(e.request).then(res=>{ if(res.ok||res.type==='opaque'){ const cp=res.clone(); caches.open(C).then(c=>c.put(e.request,cp)) } return res })));
});

const C='laer-norsk-v33';
const ASSETS=['./','./index.html','./manifest.json','./icon-192.png','./icon-512.png','./apple-touch-icon.png'];
self.addEventListener('install',e=>{ e.waitUntil(caches.open(C).then(c=>c.addAll(ASSETS))); self.skipWaiting() });
self.addEventListener('activate',e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))); self.clients.claim() });
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  e.respondWith(caches.match(e.request,{ignoreSearch:true}).then(hit=>{
    const net=fetch(e.request).then(res=>{ if(res&&(res.ok||res.type==='opaque')){ const cp=res.clone(); caches.open(C).then(c=>c.put(e.request,cp)) } return res });
    return hit||net.catch(()=>caches.match('./index.html'));
  }));
});

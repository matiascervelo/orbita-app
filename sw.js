const CACHE='orbita-piloto-04';
const ASSETS=['./','./index.html','./styles.css?v=5','./app.js?v=5','./manifest.webmanifest','./icons/favicon.svg','./icons/icon-192.png','./icons/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==CACHE).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 if(e.request.method!=='GET' || new URL(e.request.url).origin!==self.location.origin)return;
 if(new URL(e.request.url).pathname.endsWith('/data/briefing.json')) { e.respondWith(fetch(e.request));return; }
 e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy)).catch(()=>{})}return r}).catch(()=>caches.match(e.request)));
});


const CACHE="sgk-sns-v1";
const ASSETS=["/","/static/style.css","/static/app.js","/static/icon.svg","/static/manifest.json"];
self.addEventListener("install",e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener("fetch",e=>{
  if(e.request.method!=="GET") return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});

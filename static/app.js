const el = id => document.getElementById(id);
const labels = {hitap:'Başkanlığa hitap',milletvekili:'Milletvekili adı',secim_cevresi:'Seçim çevresi',muhatap:'Muhatap adı ve unvanı',talep:'Talep ifadesi',harf:'Büyük–küçük harf'};
const states = {uygun:'Uygun',uyari:'Şekil uyarısı',belirsiz:'İnsan kontrolü gerekli',kaynak_yok:'Kaynakta kayıt yok',uyumlu:'Okuma uyumlu',uyusmazlik:'Okuma uyuşmazlığı',ocr_yok:'PDF metin katmanı yok'};
let configured = false, busy = false, report = null, previewReady = false;
function node(tag, text, className) { const n = document.createElement(tag); n.textContent = text; if(className)n.className=className; return n; }
function status(text,error=false){el('status').textContent=text;el('status').className=error?'error':'';}
function buttons(){el('review').disabled=busy||!configured||!previewReady||!el('document').files[0];el('document').disabled=busy;el('download').disabled=busy||!report;}
async function health(){try{const r=await fetch('/api/health');if(!r.ok)throw Error();const h=await r.json();configured=h.api_configured;if(!busy)status(configured?'Analiz bağlantısı yapılandırılmış. PDF seçip incelemeyi başlatabilirsiniz.':'Analiz anahtarı eksik. Sunucunun API bağlantı ayarı tamamlanana kadar inceleme başlatılamaz.',!configured);}catch{configured=false;status('Uygulama sunucusuna ulaşılamadı.',true);}buttons();}
el('document').addEventListener('change',async()=>{
 report=null;el('report').replaceChildren(node('p','Henüz analiz yapılmadı.','muted'));
 previewReady=false;el('preview').replaceChildren();
 const file=el('document').files[0];el('preview').hidden=!file;el('empty').hidden=!!file;
 if(file){if(file.size>12*1024*1024){el('document').value='';el('preview').hidden=true;el('empty').hidden=false;status('Dosya 12 MB sınırını aşıyor.',true);}else{
 busy=true;buttons();status('Belge görüntüsü hazırlanıyor…');
 try{const response=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/pdf'},body:file});const data=await response.json();if(!response.ok)throw Error(data.detail||'Belge görüntülenemedi.');data.images.forEach((base64,index)=>{const img=document.createElement('img');img.alt=`Önerge, sayfa ${index+1}`;img.src='data:image/png;base64,'+base64;el('preview').append(node('p',`Sayfa ${index+1}`,'muted'),img);});previewReady=true;status(configured?'Belge hazır. İncelemeyi başlatabilirsiniz.':'Belge seçildi; analiz anahtarı henüz eklenmedi.',!configured);}
 catch(e){status(e.message,true);el('preview').hidden=true;el('empty').hidden=false;}
 finally{busy=false;}
 }}
 buttons();
});
function render(data){
 const container=el('report');container.replaceChildren();
 container.append(node('p',data.review.summary||'Özet doğrulanamadı.','summary'));
 for(const warning of data.warnings)container.append(node('p',warning,'notice'));
 for(const check of data.review.checks){const box=node('div','','check');box.append(node('h3',labels[check.kind]),node('span',states[check.status],'tag '+check.status),node('p','Sayfa '+check.page));if(check.quote)box.append(node('blockquote',check.quote));box.append(node('p',check.explanation));container.append(box);}
 for(const page of data.comparisons){const d=document.createElement('details');d.append(node('summary',`Sayfa ${page.page} · ${states[page.state]}`));const readings=node('div','','reading');for(const [title,text] of [['PDF metin katmanı',page.ocr||'Metin katmanı yok.'],['Görüntüden okuma',page.vision]]){const column=node('div','');column.append(node('h4',title),node('pre',text));readings.append(column);}d.append(readings);for(const uncertainty of page.uncertainties)d.append(node('p',uncertainty,'notice'));if(page.diff)d.append(node('pre',page.diff,'diff'));container.append(d);}
 container.append(node('p','Belge SHA-256: '+data.document_sha256,'hash'));
}
el('review').addEventListener('click',async()=>{
 const file=el('document').files[0];if(!file||busy||!configured)return;
 busy=true;report=null;el('report').replaceChildren(node('p','Belge inceleniyor…'));buttons();status('Sayfalar okunuyor ve şekil kontrolleri yapılıyor. Bu işlem birkaç dakika sürebilir.');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),180000);
 try{const response=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/pdf'},body:file,signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.detail||'İnceleme tamamlanamadı.');report=data;render(data);status('İnceleme tamamlandı. Belirsizlikleri ve dayanakları özgün belgeyle kontrol edin.');}
 catch(e){status(e.name==='AbortError'?'İstek zaman aşımına uğradı; inceleme tamamlanamadı.':e.message,true);el('report').replaceChildren(node('p','Analiz tamamlanmadı. Yukarıdaki hata açıklamasını kontrol edin.','notice'));}
 finally{clearTimeout(timer);busy=false;buttons();}
});
el('download').addEventListener('click',()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='onerge-raporu.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
health();
window.addEventListener('focus',()=>{if(!busy)health();});

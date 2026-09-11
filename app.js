
const $=id=>document.getElementById(id);
let photoState=[];

$("photos").addEventListener("change",()=>{
  photoState=[...$("photos").files].map((file,i)=>({file,index:i,needsEdit:null,editedUrl:null}));
  renderPhotos();
});

function renderPhotos(){
  const box=$("photoList"); box.innerHTML="";
  photoState.forEach((p,i)=>{
    const d=document.createElement("div"); d.className="photo";
    const img=document.createElement("img"); img.src=URL.createObjectURL(p.file);
    const info=document.createElement("div");
    info.innerHTML=`<div class="name">${p.file.name}</div><div class="status">${p.needsEdit===null?"미판별":p.needsEdit?"편집 필요":"원본 사용 가능"}</div>`;
    const mark=document.createElement("div"); mark.textContent=p.needsEdit?"🔒":p.needsEdit===false?"✓":"";
    d.append(img,info,mark); box.appendChild(d);
    if(p.editedUrl){
      const e=document.createElement("div"); e.className="edited";
      e.innerHTML=`<img src="${p.editedUrl}"><a class="download" href="${p.editedUrl}" download>편집본 저장</a>`;
      box.appendChild(e);
    }
  })
}

function busy(on,text="처리 중..."){$("busy").classList.toggle("hidden",!on);$("busyText").textContent=text}

async function checkPhotos(){
  if(!photoState.length){alert("사진을 먼저 선택해 주세요.");return}
  busy(true,"사진 개인정보 보호 판별 중...");
  try{
    for(let i=0;i<photoState.length;i++){
      $("busyText").textContent=`사진 판별 ${i+1}/${photoState.length}`;
      const fd=new FormData();fd.append("file",photoState[i].file);
      const r=await fetch("/api/privacy-check",{method:"POST",body:fd});
      if(!r.ok)throw new Error(await r.text());
      const j=await r.json(); photoState[i].needsEdit=!!j.needs_edit; photoState[i].reason=j.reason;
      renderPhotos();
    }
  }catch(e){alert("판별 오류: "+e.message)}finally{busy(false)}
}

async function editNeeded(){
  if(!photoState.length){alert("사진을 먼저 선택해 주세요.");return}
  if(photoState.some(p=>p.needsEdit===null)){await checkPhotos()}
  const targets=photoState.filter(p=>p.needsEdit);
  if(!targets.length){alert("비식별 편집이 필요한 사진이 없습니다.");return}
  busy(true,"비식별 사진 생성 중...");
  try{
    for(let i=0;i<targets.length;i++){
      $("busyText").textContent=`사진 편집 ${i+1}/${targets.length}`;
      const fd=new FormData();fd.append("file",targets[i].file);
      const r=await fetch("/api/privacy-edit",{method:"POST",body:fd});
      if(!r.ok)throw new Error(await r.text());
      const j=await r.json(); targets[i].editedUrl=j.url; renderPhotos();
    }
  }catch(e){alert("편집 오류: "+e.message)}finally{busy(false)}
}

async function generateContent(){
  const lesson=$("lesson").value.trim();
  if(!lesson){alert("오늘 수업 내용을 입력해 주세요.");return}
  busy(true,"블로그와 인스타 글 생성 중...");
  try{
    const fd=new FormData();
    fd.append("branch",$("branch").value);
    fd.append("content_type",$("contentType").value);
    fd.append("target",$("target").value);
    fd.append("lesson",lesson);
    const r=await fetch("/api/generate",{method:"POST",body:fd});
    if(!r.ok)throw new Error(await r.text());
    const j=await r.json();
    $("result").value=j.text;
    $("keywords").innerHTML=j.keywords.map(x=>`<span class="chip">#${x}</span>`).join("");
  }catch(e){alert("생성 오류: "+e.message)}finally{busy(false)}
}

async function copyResult(){
  await navigator.clipboard.writeText($("result").value); alert("복사했습니다.");
}
async function shareResult(){
  const text=$("result").value;
  if(navigator.share){await navigator.share({title:"생각키움 SNS 콘텐츠",text})}
  else{await navigator.clipboard.writeText(text);alert("공유 기능을 지원하지 않아 복사했습니다.")}
}
if("serviceWorker" in navigator){navigator.serviceWorker.register("/static/sw.js")}

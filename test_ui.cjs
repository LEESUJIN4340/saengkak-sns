const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(__dirname + '/static/index.html','utf8');
const code=html.split('<script>')[1].split('</script>')[0];
const els=new Map();
function el(id){if(!els.has(id))els.set(id,{value:'',textContent:'',innerHTML:'',style:{},classList:{add(){},remove(){}},replaceChildren(){},appendChild(){},addEventListener(){},scrollIntoView(){}});return els.get(id);}
const storage=new Map();let sent;
const context={console,FormData,AbortController,URL,Blob,setTimeout:()=>1,clearTimeout(){},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 window:{addEventListener(){}},document:{getElementById:el,querySelector:()=>el('quality'),querySelectorAll:()=>[],createElement:()=>el('created')},
 navigator:{clipboard:{writeText:async()=>{}}},fetch:async(url,req)=>{sent=req.body;return{ok:true,json:async()=>({text:'===제목후보===\n1. 생각키움연구소\n추천: 생각키움연구소\n===블로그본문===\n**소제목**\n<script>alert(1)</script>\n===인스타그램===\n수업\n===해시태그===\n#체스\n===대표이미지문구===\n생각\n===SEO품질점수===\n점검',checks:{items:[],editor_review:[],missing_info:[]},keyword:'운양동 체스학원'})}}};
vm.createContext(context);vm.runInContext(code,context);
(async()=>{
 el('branch').value='장기점';context.loadBranchProfile();assert.equal(el('keyword').value,'장기동 체스학원');
 el('profilePhone').value='010-1234-5678';context.saveBranchProfile(true);
 el('branch').value='사우점';context.loadBranchProfile();assert.equal(el('profilePhone').value,'');
 el('branch').value='장기점';context.loadBranchProfile();assert.equal(el('profilePhone').value,'010-1234-5678');
 storage.set('sns_history',JSON.stringify([{title:'지난 글',body:'이전 수업'}]));
 el('lesson').value='핀과 포크 비교';el('intent').value='지역 학원 찾기';el('target').value='초등 전체';el('content_type').value='수업후기';
 await context.generate();assert.equal(sent.get('intent'),'지역 학원 찾기');assert(sent.get('recent_posts').includes('지난 글'));assert(sent.get('branch_profile').includes('010-1234-5678'));
 assert(el('blogBody').innerHTML.includes('&lt;script&gt;'));assert(!el('blogBody').innerHTML.includes('<script>'));
 assert.equal(context.safeWebUrl('javascript:alert(1)'),'');
 context.renderSeoScore({items:[],editor_review:[],missing_info:[]});assert(el('quality').innerHTML.includes('AI 편집 의견'));
 context.fetch=async()=>({ok:false,json:async()=>({detail:'사용 한도 확인'})});await context.generate();assert.equal(el('toast').textContent,'사용 한도 확인');assert.equal(el('genBtn').disabled,false);
 console.log('JavaScript integration checks passed: branch isolation, request fields, history context, HTML escaping, checklist, errors.');
})().catch(e=>{console.error(e);process.exit(1)});

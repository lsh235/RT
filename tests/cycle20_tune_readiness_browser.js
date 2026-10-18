async page => {
globalThis.cycle20Mode = 'not-ready';
const consoleErrors = [];
page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204, body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  if (url.pathname === '/api/concepts/tune/readiness') {
    if (globalThis.cycle20Mode === 'error') return route.fulfill({status:200,contentType:'application/json',body:'{invalid json'});
    if (globalThis.cycle20Mode === 'malformed') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({eligible:true,reason_code:'train_positive_available',scope:'label_readiness_only',counts:{training_queries:1}})});
    if (globalThis.cycle20Mode === 'delayed') await new Promise(resolve => setTimeout(resolve, 650));
    const ready = globalThis.cycle20Mode === 'ready';
    const counts = {
      training_queries:4,training_graded:3,training_positive:ready?2:0,training_graded_queries:3,
      training_positive_queries:ready?2:0,validation_queries:2,validation_graded:1,validation_positive:1,
      validation_graded_queries:1,validation_positive_queries:1,training_information_need_groups:2,
      training_graded_information_need_groups:2,training_positive_information_need_groups:ready?1:0,
      validation_information_need_groups:1,validation_graded_information_need_groups:1,
      validation_positive_information_need_groups:1,stale:2
    };
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      eligible:ready,reason_code:ready?'train_positive_available':'train_positive_required',scope:'label_readiness_only',counts
    })});
  }
  if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
  if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'synthetic'})});
  if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  return route.fulfill({status:200,contentType:'application/json',body:'{}'});
});
await page.reload();
await page.waitForTimeout(300);
const require = (condition,message) => { if (!condition) throw new Error(message); };
const initial = await page.evaluate(() => ({status:document.querySelector('#tune-readiness')?.textContent||'',detail:document.querySelector('#tune-readiness-detail')?.innerText||''}));
require(initial.status.includes('개념을 저장') && initial.detail.includes('저장된 개념이 없습니다'),`empty concept state is unclear: ${JSON.stringify(initial)}`);

await page.evaluate(() => {
  state.schema=[{name:'body',type:'text',searchable:true,filterable:false,nested:false}]; state.schemaIndex='synthetic-index';
  document.querySelector('#index-name').value='synthetic-index';
  const concept={id:'cycle20-browser',name:'Synthetic concept',description:'Fixture',aliases:[],related:[],excluded_terms:[],
    corpus:{index:'synthetic-index',title_field:'',text_fields:['body'],filter_fields:[]},filters:[],
    settings:{mode:'bm25',size:5,candidate_size:5,concept_weight:1,related_weight:1,field_boosts:{body:1}},
    queries:[{id:'q-train',query:'training query',split:'train',information_need:'Need A'},
      {id:'q-val',query:'validation query',split:'validation',information_need:'Need B'}]};
  populateConcept(concept); state.connected=true; state.conceptId=concept.id;
  state.savedConceptSnapshot=JSON.stringify(collectConcept()); updateTuneReadiness();
});
const waitFor = () => page.waitForFunction(() => !document.querySelector('#tune-readiness').textContent.includes('확인하고 있습니다'));
await page.waitForTimeout(60);
const loading=await page.evaluate(()=>({status:document.querySelector('#tune-readiness').textContent,detail:document.querySelector('#tune-readiness-detail').textContent}));
require(loading.status.includes('확인하고 있습니다')&&loading.detail.includes('불러오는 중'),`loading state is unclear: ${JSON.stringify(loading)}`);
await waitFor();
const notReady = await page.evaluate(() => ({status:document.querySelector('#tune-readiness').textContent,
 detail:document.querySelector('#tune-readiness-detail').innerText,live:document.querySelector('#tune-readiness').getAttribute('aria-live'),
 detailLive:document.querySelector('#tune-readiness-detail').getAttribute('aria-live'),buttonDisabled:document.querySelector('#concept-tune').disabled,
 disclosureTag:document.querySelector('#tune-readiness-detail details.readiness-details')?.tagName||'',caveat:document.querySelector('.readiness-caveat')?.innerText||''}));
require(notReady.status.includes('학습용')&&notReady.detail.includes('별도 확인용 평가만으로는 준비되지 않습니다'),`not-ready state lacks a plain positive training grade requirement: ${JSON.stringify(notReady)}`);
require(notReady.status.length<40 && !/품질|적절|충분|대표성/.test(notReady.status),`concise readiness status contains quality or adequacy judgment: ${notReady.status}`);
require(notReady.live==='polite'&&notReady.disclosureTag==='DETAILS'&&notReady.detailLive===null,`status/disclosure accessibility semantics changed: ${JSON.stringify(notReady)}`);
require(notReady.caveat.length>0&&/품질|대표성/.test(notReady.caveat),`visible caveat about representativeness/quality is missing: ${JSON.stringify(notReady)}`);
require(!notReady.buttonDisabled,`server-authoritative tune gating behavior changed: ${JSON.stringify(notReady)}`);
const summary = await page.locator('#tune-readiness-detail details summary');
await summary.focus(); await page.keyboard.press('Enter');
require(await page.locator('#tune-readiness-detail details').evaluate(el=>el.open),'native disclosure did not open with Enter');
await page.keyboard.press('Enter');
require(!(await page.locator('#tune-readiness-detail details').evaluate(el=>el.open)),'native disclosure did not close with Enter');
await summary.click();
const expanded = await page.locator('#tune-readiness-detail').innerText();
for (const text of ['평가 3개·양수 0개','평가 질의 3/4개','양수 평가 0/4개','정보 요구 묶음 2/2개','평가 1개·양수 1개','평가 질의 1/2개','정보 요구 묶음 1/1개','오래된 평가 제외 2개','최소 개수 기준은 없고','실제 사용 대표성이나 검색 품질을 예측하지 않습니다']) require(expanded.includes(text),`expanded counts/caveat missing “${text}”: ${expanded}`);
require(!/adequate|검색 품질이|품질이 향상|충분히|충분한/i.test(expanded),`expanded disclosure implies quality/adequacy: ${expanded}`);

globalThis.cycle20Mode='ready'; await page.evaluate(()=>updateTuneReadiness()); await waitFor();
await page.locator('#tune-readiness-detail details summary').click();
const ready = await page.evaluate(()=>({status:document.querySelector('#tune-readiness').textContent,detail:document.querySelector('#tune-readiness-detail').innerText}));
require(ready.status.includes('설정 비교를 시작할 수 있습니다')&&ready.status.length<40,`ready state is not concise: ${JSON.stringify(ready)}`);
require(ready.detail.includes('학습용 문서')&&!/검색 품질|결과가 좋|충분히/.test(ready.status)&&ready.detail.includes('검색 품질을 예측하지 않습니다'),`readiness was conflated with retrieval quality or omitted its caveat: ${JSON.stringify(ready)}`);
require(ready.detail.includes('평가 3개·양수 2개')&&ready.detail.includes('평가 질의 3/4개')&&ready.detail.includes('오래된 평가 제외 2개'),`rendered ready details do not match fixture counts: ${JSON.stringify(ready)}`);

globalThis.cycle20Mode='malformed'; await page.evaluate(()=>updateTuneReadiness()); await waitFor();
const malformed=await page.evaluate(()=>({status:document.querySelector('#tune-readiness').textContent,detail:document.querySelector('#tune-readiness-detail').innerText}));
require(malformed.status.includes('확인하지 못했습니다')&&malformed.detail.includes('서버가 준비 상태를 다시 확인합니다'),`malformed response is misleading/unhandled: ${JSON.stringify(malformed)}`);
globalThis.cycle20Mode='error'; await page.evaluate(()=>updateTuneReadiness()); await waitFor();
const failed=await page.evaluate(()=>({status:document.querySelector('#tune-readiness').textContent,detail:document.querySelector('#tune-readiness-detail').innerText}));
require(failed.status.includes('확인하지 못했습니다')&&failed.detail.includes('서버가 준비 상태를 다시 확인합니다'),`API error state is unclear: ${JSON.stringify(failed)}`);

globalThis.cycle20Mode='delayed'; await page.evaluate(()=>updateTuneReadiness());
await page.waitForTimeout(300);
await page.evaluate(()=>{document.querySelector('#concept-name').value='Changed while pending'; document.querySelector('#concept-name').dispatchEvent(new Event('input',{bubbles:true}));});
await page.waitForTimeout(700);
const stale=await page.evaluate(()=>({status:document.querySelector('#tune-readiness').textContent,detail:document.querySelector('#tune-readiness-detail').innerText}));
require(!stale.status.includes('설정 비교를 시작할 수 있습니다')&&!stale.detail.includes('평가 3개'),`stale readiness response overwrote newer concept state: ${JSON.stringify(stale)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.scrollWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors after mocked reload: ${JSON.stringify(consoleErrors)}`);
console.log(JSON.stringify({initial,loading,notReady,ready,malformed,failed,stale,mobile,consoleErrors}));
}

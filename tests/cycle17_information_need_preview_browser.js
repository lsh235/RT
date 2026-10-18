async page => {
globalThis.cycle17Mode = 'complete';
await page.route('**/api/**', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/api/concepts/information-need-preview') {
    if (globalThis.cycle17Mode === 'delay') {
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    const partial = globalThis.cycle17Mode === 'partial';
    const okPreview = id => ({
      baseline: {hits: [{_index:'synthetic-index', _id:`${id}-baseline`, _score:1, rank:1, source:{body:'synthetic result'}, snippet:'synthetic result', evidence:[]}], total:1},
      candidate: {hits: [{_index:'synthetic-index', _id:`${id}-candidate`, _score:2, rank:1, organic_rank:1, source:{body:'synthetic result'}, snippet:'synthetic result', evidence:[], judgment:{rating:null,pinned:false,reason:''}}], total:1},
      comparison: []
    });
    const result = {information_need:'Recovery', split:'train', count:2, status: partial?'partial':'complete', results:[
      {query_id:'q-a',query:'recover request',split:'train',preview:okPreview('q-a')},
      ...(!partial ? [{query_id:'q-b',query:'resume after retry',split:'train',preview:okPreview('q-b')}] : [])
    ], failures: partial ? [{query_id:'q-b',query:'resume after retry',split:'train',error:'synthetic unavailable'}] : []};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  }
  if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
  if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
  if (url.pathname === '/api/concepts/save') {
    const body = route.request().postDataJSON();
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concept:body.concept,version_id:'synthetic-version'})});
  }
  if (url.pathname === '/api/concepts/ensure-query') {
    const body = route.request().postDataJSON();
    const query_id = body.query === 'resume after retry' ? 'q-b' : 'q-a';
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({query_id})});
  }
  if (url.pathname === '/api/concepts/preview') {
    const body = route.request().postDataJSON();
    const query = body.query || (body.query_id === 'q-b' ? 'resume after retry' : 'recover request');
    const id = body.query_id || 'q-b';
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      query, baseline:{hits:[{_index:'synthetic-index',_id:`${id}-ordinary-base`,_score:1,rank:1,source:{body:'ordinary result'},snippet:'ordinary result',evidence:[]}],total:1},
      candidate:{hits:[{_index:'synthetic-index',_id:`${id}-ordinary-candidate`,_score:2,rank:1,organic_rank:1,source:{body:'ordinary result'},snippet:'ordinary result',evidence:[],judgment:{rating:null,pinned:false,reason:''}}],total:1}, comparison:[]
    })});
  }
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'synthetic'})});
  if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  return route.fulfill({status:200,contentType:'application/json',body:'{}'});
});
await page.reload();
await page.waitForTimeout(300);
await page.evaluate(() => {
  state.schema = [
    {name:'body', type:'text', searchable:true, filterable:false, nested:false},
    {name:'tenant', type:'keyword', searchable:false, filterable:true, nested:false}
  ];
  state.schemaIndex = 'synthetic-index';
  const fixture = {
    id:'cycle17-browser', name:'Synthetic concept', description:'Synthetic acceptance description', aliases:[], related:[], excluded_terms:[],
    corpus:{index:'synthetic-index',title_field:'',text_fields:['body'],filter_fields:['tenant']},
    filters:[{field:'tenant',value:'alpha'}], settings:{mode:'bm25',size:2,candidate_size:5,concept_weight:1,related_weight:1,field_boosts:{body:1}},
    queries:[
      {id:'q-a',query:'recover request',split:'train',information_need:'Recovery'},
      {id:'q-b',query:'resume after retry',split:'train',information_need:' recovery '}
    ]
  };
  window.__cycle17Fixture = fixture;
  populateConcept(fixture);
  const saved = document.querySelector('#saved-concepts');
  saved.innerHTML = '<option value="cycle17-browser">Synthetic concept</option>';
  saved.value = 'cycle17-browser';
  state.connected = true;
  state.conceptId = fixture.id;
  state.savedConceptSnapshot = JSON.stringify(collectConcept());
  refreshQueryChoices('q-a');
  document.querySelector('#concept-query-select').value = 'q-a';
  state.savedConceptSnapshot = JSON.stringify(collectConcept());
  updateInformationNeedPreviewAction();
});
const sizeGuard = await page.evaluate(() => {
  const fixture = window.__cycle17Fixture;
  const selectFixture = concept => {
    populateConcept(concept);
    document.querySelectorAll('.concept-query-row').forEach(row => { row.dataset.queryEnsured = 'true'; });
    document.querySelector('#saved-concepts').innerHTML = `<option value="${concept.id}">Synthetic concept</option>`;
    document.querySelector('#saved-concepts').value = concept.id;
    state.connected = true;
    state.conceptId = concept.id;
    refreshQueryChoices('q-a');
    document.querySelector('#concept-query-select').value = 'q-a';
    state.savedConceptSnapshot = JSON.stringify(collectConcept());
    updateInformationNeedPreviewAction();
  };
  selectFixture({...fixture, queries:[fixture.queries[0]]});
  const singleton = {disabled:document.querySelector('#information-need-preview').disabled, title:document.querySelector('#information-need-preview').title};
  const tooMany = {...fixture, queries:[...fixture.queries, ...Array.from({length:9}, (_,i)=>({id:`extra-${i}`,query:`extra phrasing ${i}`,split:'train',information_need:'Recovery'}))]};
  selectFixture(tooMany);
  const oversized = {disabled:document.querySelector('#information-need-preview').disabled, title:document.querySelector('#information-need-preview').title};
  selectFixture(fixture);
  return {singleton,oversized};
});
if (!sizeGuard.singleton.disabled || !sizeGuard.singleton.title.includes('두 개 이상') || !sizeGuard.oversized.disabled || !sizeGuard.oversized.title.includes('최대 10개')) throw new Error(`size guard mismatch ${JSON.stringify(sizeGuard)}`);
await page.locator('#information-need-preview').click();
await page.waitForFunction(() => document.querySelectorAll('.information-need-query-card').length === 2);
const complete = await page.evaluate(() => ({
  cards: [...document.querySelectorAll('.information-need-query-card > h3')].map(x=>x.textContent),
  queryIds: [...document.querySelectorAll('.information-need-query-card .judge-controls')].map(x=>x.dataset.queryId),
  status: document.querySelector('#concept-preview-status').textContent,
  errors: 0
}));
if (complete.cards.length !== 2 || !complete.queryIds.includes('q-a') || !complete.queryIds.includes('q-b')) throw new Error(`complete/cards mismatch ${JSON.stringify(complete)}`);
await page.setViewportSize({width:390,height:844});
const mobileOverflow = await page.evaluate(() => ({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth}));
if (mobileOverflow.scrollWidth > mobileOverflow.width) throw new Error(`mobile horizontal overflow ${JSON.stringify(mobileOverflow)}`);
await page.setViewportSize({width:1280,height:900});
// Reuse the same UI and verify a partial response is shown as a failure, not an empty-result card.
globalThis.cycle17Mode = 'partial';
await page.locator('#information-need-preview').click();
await page.waitForFunction(() => document.querySelector('.notice-error')?.textContent.includes('synthetic unavailable'));
const partial = await page.evaluate(() => ({
  cards: document.querySelectorAll('.information-need-query-card').length,
  status: document.querySelector('#concept-preview-status').textContent,
  failure: document.querySelector('.notice-error')?.textContent || ''
}));
if (partial.cards !== 1 || !partial.status.includes('부분 완료') || !partial.failure.includes('synthetic unavailable')) throw new Error(`partial mismatch ${JSON.stringify(partial)}`);
// Delayed response must not replace content after the selected query changes.
globalThis.cycle17Mode = 'delay';
const changedContextResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/concepts/information-need-preview' && response.status() === 200);
await page.locator('#information-need-preview').click();
await page.waitForTimeout(50);
await page.evaluate(() => {
  const select = document.querySelector('#concept-query-select');
  select.value = 'q-b';
  select.dispatchEvent(new Event('change', {bubbles:true}));
  document.querySelector('#concept-preview-status').textContent = 'context changed';
});
const changedResponse = await changedContextResponse;
await changedResponse.finished();
await page.waitForTimeout(50);
const stale = await page.evaluate(() => ({status:document.querySelector('#concept-preview-status').textContent, cards:document.querySelectorAll('.information-need-query-card').length}));
if (stale.status !== 'context changed' || stale.cards !== 0) throw new Error(`stale response mismatch ${JSON.stringify(stale)}`);
// A normal preview started while the group request is pending supersedes that older response.
globalThis.cycle17Mode = 'delay';
const supersededGroupResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/concepts/information-need-preview' && response.status() === 200);
await page.locator('#information-need-preview').click();
await page.waitForTimeout(50);
const ordinaryResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/concepts/preview' && response.status() === 200);
await page.evaluate(() => runConceptPreview());
const ordinaryDone = await ordinaryResponse;
await ordinaryDone.finished();
await page.waitForFunction(() => document.querySelector('#concept-preview-status').textContent.includes('비교 완료'));
const ordinaryVisible = await page.evaluate(() => ({status:document.querySelector('#concept-preview-status').textContent,ordinary:document.querySelector('#concept-preview-results').textContent.includes('ordinary result')}));
const supersededDone = await supersededGroupResponse;
await supersededDone.finished();
await page.waitForTimeout(50);
const afterSuperseded = await page.evaluate(() => ({status:document.querySelector('#concept-preview-status').textContent,ordinary:document.querySelector('#concept-preview-results').textContent.includes('ordinary result'),groupCards:document.querySelectorAll('.information-need-query-card').length}));
if (!ordinaryVisible.ordinary || !afterSuperseded.ordinary || afterSuperseded.groupCards !== 0 || afterSuperseded.status !== ordinaryVisible.status) throw new Error(`ordinary preview was overwritten by stale group response ${JSON.stringify({ordinaryVisible,afterSuperseded})}`);
console.log(JSON.stringify({sizeGuard,complete,partial,stale,mobileOverflow,ordinaryVisible,afterSuperseded}));

}

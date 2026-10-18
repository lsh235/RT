async page => {
  const calls = [];
  const consoleErrors = [];
  const pageErrors = [];
  const require = (condition, message) => { if (!condition) throw new Error(message); };
  const comparison = {
    concept_id: 'cycle34-ui', query_id: 'train-q', query: '<img src=x onerror=alert(1)>', split: 'train',
    index: 'cycle34-alias', settings_size: 3,
    effective_filters: [{field:'status',value:'Open'}], filters_fingerprint:'abc123',
    judgments_applied_to_current_filters:true,
    metrics: {
      concept_bm25:{status:'available',k:3,ndcg_at_k:0.7,judged_coverage_at_k:0.5,recall_of_judged_relevant_at_k:0,judged_count:2,positive_judged_count:1,relevant_found_at_k:0,retrieved_judged_count:1,unjudged_retrieved_count:2,explicit_unjudged_count:1,stale_judgment_count:2},
      e5_vector:{status:'no_positive_judgments',k:3,ndcg_at_k:null,judged_coverage_at_k:0,recall_of_judged_relevant_at_k:null,judged_count:2,positive_judged_count:0,relevant_found_at_k:0,retrieved_judged_count:0,unjudged_retrieved_count:3,explicit_unjudged_count:1,stale_judgment_count:2}
    },
    vector:{approximate:true,exhaustive:false,candidate_count:3,candidate_limit:3,total:14},
    bm25:{candidate_count:3},
    limits:['현재 필터 범위의 제한된 후보 비교입니다. 코퍼스 전체 품질을 보장하지 않습니다.']
  };
  await page.goto('about:blank');
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    let body={};
    try { if (route.request().method()==='POST') body=route.request().postDataJSON(); } catch {}
    calls.push({path:url.pathname,body});
    if(url.pathname==='/api/auth/session') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({configured:true,authenticated:true,user:{id:'cycle34-admin',username:'cycle34-admin',display_name:'Cycle 34 Admin',role:'admin'},csrf_token:'cycle34-session-csrf'})});
    if(url.pathname==='/api/admin/accounts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({accounts:[]})});
    if (url.pathname==='/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.22.0'})});
    if (url.pathname==='/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    if (url.pathname==='/api/ai/status') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[]})});
    if (url.pathname==='/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
    if (url.pathname==='/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
    if (url.pathname==='/api/concepts/mode-comparison') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(comparison)});
    if (url.pathname==='/api/concepts/preview') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({query:'saved retry query',baseline:{hits:[{_index:'cycle34-index',_id:'bm25-doc',rank:1,organic_rank:1,title:'BM25 result',source:{body:'synthetic BM25 result'},judgment:{rating:null,pinned:false,reason:''}}],total:1},candidate:{hits:[{_index:'cycle34-index',_id:'bm25-doc',rank:1,organic_rank:1,title:'BM25 result',source:{body:'synthetic BM25 result'},judgment:{rating:null,pinned:false,reason:''}}],total:1},comparison:[],warnings:[]})});
    if (url.pathname==='/api/concepts/vector-candidates') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concept_id:'cycle34-ui',query_id:'train-q',query:'saved retry query',index:'cycle34-alias',mode:'vector',model:'synthetic-local',field:'rag_embedding',dimensions:1024,approximate:true,exhaustive:false,total:1,candidates:[{_index:'cycle34-index',_id:'vector-doc',_score:0.8,rank:1,source:{body:'synthetic vector result'},source_sha256:'synthetic',snippet:'synthetic vector result',judgment:{rating:null,pinned:false,reason:''}}]})});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  });
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  page.on('pageerror',e=>pageErrors.push(String(e)));
  await page.goto(process.env.CYCLE37_BASE_URL || 'http://127.0.0.1:18782/');
  await page.waitForFunction(()=>document.querySelector('#server-version')?.textContent.trim()==='v0.22.0');
  await page.waitForFunction(()=>!document.querySelector('#workbench-layout')?.classList.contains('hidden'));
  await page.evaluate(() => {
    state.connected=true;
    state.schema=[
      {name:'body',type:'text',searchable:true,filterable:false,nested:false},
      {name:'status',type:'keyword',searchable:false,filterable:true,nested:false}
    ];
    const concept={id:'cycle34-ui',name:'Retry recovery',description:'failed requests',aliases:[],related:[],excluded_terms:[],
      corpus:{index:'cycle34-alias',title_field:'',text_fields:['body'],filter_fields:['status']},
      filters:[{field:'status',value:'Open'}],settings:{mode:'bm25',size:3,candidate_size:10},
      queries:[{id:'train-q',query:'saved retry query',split:'train'}]};
    populateConcept(concept);
    state.conceptId=concept.id;
    state.savedConceptSnapshot=JSON.stringify(collectConcept());
    document.querySelector('#saved-concepts').innerHTML='<option value="cycle34-ui">Retry recovery</option>';
    document.querySelector('#saved-concepts').value='cycle34-ui';
    document.querySelector('#concept-query-select').value='train-q';
    state.preview={conceptId:'cycle34-ui',queryId:'train-q'};
    updateModeComparisonAction();
  });
  const button=page.locator('#concept-mode-comparison');
  require(await button.isEnabled(),'comparison action is not enabled for a saved, previewed query');
  const statusNode=page.locator('#concept-mode-comparison-status');
  require(await statusNode.getAttribute('aria-live')==='polite','comparison status is not announced politely');
  await button.focus();
  await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#concept-mode-comparison-status')?.textContent.includes('비교 완료'));
  const request=calls.find(call=>call.path==='/api/concepts/mode-comparison');
  require(Boolean(request),'keyboard activation did not invoke comparison');
  require(request.body.concept_id==='cycle34-ui'&&request.body.query_id==='train-q','request omitted selected saved concept/query identity');
  require(!('query' in request.body)&&!('filters' in request.body)&&!('size' in request.body),'client sent mutable retrieval parameters');
  const result=page.locator('#concept-mode-comparison-results');
  const text=await result.innerText();
  require(text.includes('status = Open')&&text.includes('abc123'),'filter scope or fingerprint is hidden');
  require(text.includes('근사 예')&&text.includes('전체 검색 아님')&&text.includes('코퍼스 전체 품질'),'candidate limits are not visible');
  require(text.includes('평가가 있는 문서만으로 계산했습니다.')||text.includes('관련 있다고 평가한 문서가 없어 순위 점수를 계산할 수 없습니다.'),'metric interpretation state is missing');
  require(text.includes('—'),'null metric is not shown distinctly');
  require(!await result.locator('img').count(),'untrusted query HTML was rendered');
  require(await result.locator('code').innerText()==='abc123','filter fingerprint was not rendered as text');
  const pathCount=calls.filter(call=>call.path==='/api/concepts/mode-comparison').length;
  require(pathCount===1,'comparison request was not issued exactly once');
  await page.evaluate(()=>runConceptPreview('train-q'));
  await page.waitForFunction(()=>document.querySelector('#concept-preview-status')?.textContent.includes('비교 완료'));
  require((await page.locator('#concept-preview-results').innerText()).includes('BM25 result'),'existing BM25 concept preview was broken by mode comparison');
  require(await page.locator('#concept-vector-candidates').isEnabled(),'existing vector-candidate flow was disabled after BM25 preview');
  await page.locator('#concept-vector-candidates').click();
  await page.waitForFunction(()=>document.querySelector('#concept-vector-results')?.textContent.includes('vector-doc'));
  require(calls.filter(call=>call.path==='/api/concepts/preview').length===1,'existing BM25 preview was not called exactly once');
  require(calls.filter(call=>call.path==='/api/concepts/vector-candidates').length===1,'existing vector-candidate flow was not called exactly once');
  require((await page.locator('#concept-vector-status').innerText()).includes('각 검색 안의 순위만 표시'),'existing vector rank guidance disappeared');
  await button.click();
  await page.waitForFunction(()=>document.querySelector('#concept-mode-comparison-status')?.textContent.includes('비교 완료'));
  require(calls.filter(call=>call.path==='/api/concepts/mode-comparison').length===2,'mode comparison did not remain usable after existing preview/vector flows');
  await page.setViewportSize({width:390,height:844});
  const dimensions=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,body:document.body.scrollWidth,grid:getComputedStyle(document.querySelector('.mode-metric-grid')).gridTemplateColumns}));
  require(dimensions.body<=dimensions.viewport,`comparison overflows mobile viewport: ${JSON.stringify(dimensions)}`);
  require(dimensions.grid.split(' ').length===1,`metric cards are not stacked at mobile width: ${JSON.stringify(dimensions)}`);
  require(consoleErrors.length===0,`browser console errors: ${JSON.stringify(consoleErrors)}`);
  require(pageErrors.length===0,`browser page errors: ${JSON.stringify(pageErrors)}`);
  return {result:'PASS',request,renderedText:text,dimensions,consoleErrors,pageErrors};
}

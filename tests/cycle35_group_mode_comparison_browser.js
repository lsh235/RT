async page => {
  const calls = [], consoleErrors = [], pageErrors = [];
  const require = (ok, message) => { if (!ok) throw new Error(message); };
  const comparison = {
    concept_id:'cycle35-ui', anchor_query_id:'q1', information_need:'Retry owner', split:'train', status:'complete', selected_count:2, completed_count:2, failed_count:0,
    queries:[
      {query_id:'q1',query:'<img src=x onerror=alert(1)>',split:'train',status:'complete',bm25:{ranked_identities:[['idx-a','same']]},e5_vector:{ranked_identities:[['idx-b','same']]},metrics:{concept_bm25:{ndcg_at_k:0.8},e5_vector:{ndcg_at_k:0.7}}},
      {query_id:'q2',query:'who owns recovery',split:'train',status:'complete',bm25:{ranked_identities:[['idx-a','same']]},e5_vector:{ranked_identities:[['idx-b','same']]},metrics:{concept_bm25:{ndcg_at_k:0.4},e5_vector:{ndcg_at_k:0.5}}}
    ],
    failures:[], aggregate:{ndcg_at_k:{concept_bm25:{mean:0.6,query_count:2},e5_vector:{mean:0.6,query_count:2}},recall_of_judged_relevant_at_k:{concept_bm25:{mean:0.5,query_count:2},e5_vector:{mean:0.5,query_count:2}},judged_coverage_at_k:{concept_bm25:{mean:0.5,query_count:2},e5_vector:{mean:0.5,query_count:2}}}
  };
  const partialComparison = {
    ...comparison, status:'partial', selected_count:2, completed_count:1, failed_count:1,
    queries:[{...comparison.queries[0], metrics:{concept_bm25:{ndcg_at_k:0.8},e5_vector:{ndcg_at_k:0.7}}}],
    failures:[{query_id:'q2',query:'who owns recovery',split:'train',error:'synthetic query failure'}],
    aggregate:null
  };
  let partialMode = false;
  await page.goto('about:blank');
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    let body={}; try { if(route.request().method()==='POST') body=route.request().postDataJSON(); } catch {}
    calls.push({path:url.pathname,body});
    if(url.pathname==='/api/auth/session') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({configured:true,authenticated:true,user:{id:'cycle35-admin',username:'cycle35-admin',display_name:'Cycle 35 Admin',role:'admin'},csrf_token:'cycle35-session-csrf'})});
    if(url.pathname==='/api/admin/accounts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({accounts:[]})});
    if(url.pathname==='/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.23.0'})});
    if(url.pathname==='/api/codebase-status'||url.pathname==='/api/ai/status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    if(url.pathname==='/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
    if(url.pathname==='/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
    if(url.pathname==='/api/concepts/mode-comparison-group') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(partialMode ? partialComparison : comparison)});
    if(url.pathname==='/api/concepts/mode-comparison') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({query:'saved',metrics:{}})});
    if(url.pathname==='/api/concepts/tune') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'ready',recommendations:[]})});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  });
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  page.on('pageerror',e=>pageErrors.push(String(e)));
  await page.goto(process.env.CYCLE37_BASE_URL || 'http://127.0.0.1:18782/');
  await page.waitForFunction(()=>document.querySelector('#server-version')?.textContent.trim()==='v0.23.0');
  await page.waitForFunction(()=>!document.querySelector('#workbench-layout')?.classList.contains('hidden'));
  await page.evaluate(() => {
    state.connected=true; state.connectedIndex='cycle35-alias'; state.connectedIndexExists=true;
    document.querySelector('#index-name').value='cycle35-alias';
    state.schema=[{name:'body',type:'text',searchable:true,filterable:false,nested:false},{name:'status',type:'keyword',searchable:false,filterable:true,nested:false}];
    const concept={id:'cycle35-ui',name:'Retry recovery',description:'synthetic',aliases:[],related:[],excluded_terms:[],
      corpus:{index:'cycle35-alias',title_field:'',text_fields:['body'],filter_fields:['status']},filters:[{field:'status',value:'Open'}],settings:{mode:'bm25',size:2,candidate_size:10},
      queries:[{id:'q1',query:'saved retry owner',split:'train',information_need:'Retry owner'},{id:'q2',query:'who owns recovery',split:'train',information_need:' retry   OWNER '},{id:'q3',query:'validation',split:'validation',information_need:'different'}]};
    populateConcept(concept); state.conceptId=concept.id; state.savedConceptSnapshot=JSON.stringify(collectConcept());
    document.querySelector('#saved-concepts').innerHTML='<option value="cycle35-ui">Retry recovery</option>';
    document.querySelector('#saved-concepts').value='cycle35-ui'; document.querySelector('#concept-query-select').value='q1';
    state.preview={conceptId:'cycle35-ui',queryId:'q1'};
    if(typeof updateModeComparisonGroupAction==='function') updateModeComparisonGroupAction();
  });
  const button=page.locator('#concept-mode-comparison-group');
  require(await button.count()===1,'group comparison action is absent');
  require(await button.isEnabled(),'saved grouped query action is disabled');
  const status=page.locator('#concept-mode-comparison-group-status');
  if(await status.count()) require(await status.getAttribute('aria-live')==='polite','group status is not announced politely');
  await button.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#concept-mode-comparison-group-status')?.textContent.includes('완료'));
  const req=calls.find(c=>c.path==='/api/concepts/mode-comparison-group');
  require(Boolean(req),'keyboard activation did not request grouped comparison');
  require(req.body.concept_id==='cycle35-ui'&&req.body.query_id==='q1','request lacks saved concept and anchor query ids');
  require(!('query' in req.body)&&!('information_need' in req.body)&&!('query_ids' in req.body)&&!('filters' in req.body)&&!('size' in req.body),'client supplied caller-controlled group/search overrides');
  const result=page.locator('#concept-mode-comparison-group-results');
  const rendered=await result.innerText();
  require(rendered.includes('Retry owner')&&rendered.includes('q1')&&rendered.includes('q2'),'group label or per-query rows are hidden');
  require(rendered.includes('0.6'),'macro mean is not rendered');
  require(rendered.includes('상태: 완료'),'successful query status is not rendered in Korean');
  require(!await result.locator('img').count(),'hostile saved query markup was executed/rendered');
  // A later partial response must replace the complete result and expose the
  // failure while hiding all aggregate output and retaining paired rows only.
  partialMode = true;
  await button.click();
  await page.waitForFunction(()=>document.querySelector('#concept-mode-comparison-group-results')?.innerText.includes('synthetic query failure'));
  const partialStatus = (await status.innerText()).trim();
  const partialText = await result.innerText();
  require(/실패|부분|partial/i.test(partialStatus),`partial failure status is absent: ${partialStatus}`);
  require(partialText.includes('q2')&&partialText.includes('synthetic query failure'),'partial failure identity/reason is hidden');
  require(!partialText.includes('0.6'),'stale aggregate from the prior complete result remains visible');
  require(!partialText.includes('질의별 같은 비중 평균')&&!/macro/i.test(partialText),'partial response renders aggregate means');
  require(partialText.includes('0.8')&&partialText.includes('0.7'),'successful partial row lost its paired metrics');
  const partialRows=result.locator('.mode-group-query');
  require(await partialRows.count()===1,'failed query was rendered as a metric row');
  require((await partialRows.first().innerText()).includes('q1'),'successful paired row was replaced by the failed member');
  require(await partialRows.first().locator('.mode-metric-card').count()===2,'partial success row is missing one retrieval mode');
  await page.setViewportSize({width:390,height:844});
  const dims=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,body:document.body.scrollWidth}));
  require(dims.body<=dims.viewport,`group results overflow mobile viewport: ${JSON.stringify(dims)}`);
  // Existing one-query comparison and tune action remain separately available.
  require(await page.locator('#concept-mode-comparison').count()===1,'C34 single-query comparison control disappeared');
  require(await page.locator('#concept-tune').count()===1,'tune control disappeared');
  require(consoleErrors.length===0,`console errors: ${JSON.stringify(consoleErrors)}`);
  require(pageErrors.length===0,`page errors: ${JSON.stringify(pageErrors)}`);
  return {result:'PASS',request:req,rendered,partialStatus,partialText,dimensions:dims,consoleErrors,pageErrors};
}

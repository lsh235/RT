async page => {
  const calls = [], consoleErrors = [], pageErrors = [];
  const require = (ok, message) => { if (!ok) throw new Error(message); };
  const comparison = {
    concept_id:'cycle36-ui', anchor_query_id:'q1', information_need:'Retry owner', split:'train', status:'complete', selected_count:2, completed_count:2, failed_count:0,
    queries:[
      {query_id:'q1',query:'<img src=x onerror=alert(1)>',split:'train',status:'complete',bm25:{ranked_identities:[['idx-a','same']]},e5_vector:{ranked_identities:[['idx-b','same']]},metrics:{concept_bm25:{ndcg_at_k:0.8},e5_vector:{ndcg_at_k:0.7}}},
      {query_id:'q2',query:'who owns recovery',split:'train',status:'complete',bm25:{ranked_identities:[['idx-a','same']]},e5_vector:{ranked_identities:[['idx-b','same']]},metrics:{concept_bm25:{ndcg_at_k:0.4},e5_vector:{ndcg_at_k:0.5}}}
    ],
    failures:[], aggregate:{ndcg_at_k:{concept_bm25:{mean:0.6,query_count:2},e5_vector:{mean:0.6,query_count:2}},recall_of_judged_relevant_at_k:{concept_bm25:{mean:0.5,query_count:2},e5_vector:{mean:0.5,query_count:2}},judged_coverage_at_k:{concept_bm25:{mean:0.5,query_count:2},e5_vector:{mean:0.5,query_count:2}}}
  };
  await page.goto('about:blank');
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    let body={}; try { if(route.request().method()==='POST') body=route.request().postDataJSON(); } catch {}
    calls.push({path:url.pathname,method:route.request().method(),body});
    const json = payload => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(payload)});
    if(url.pathname==='/api/auth/session') return json({configured:true,authenticated:true,user:{id:'cycle36-admin',username:'cycle36-admin',display_name:'Cycle 36 Admin',role:'admin'},csrf_token:'cycle36-session-csrf'});
    if(url.pathname==='/api/admin/accounts/list') return json({accounts:[]});
    if(url.pathname==='/api/health') return json({version:'0.23.0'});
    if(url.pathname==='/api/codebase-status'||url.pathname==='/api/ai/status') return json({});
    if(url.pathname==='/api/connect') return json({cluster_name:'synthetic',version:'8.14.0',selected_index:'cycle36-alias',selected_index_exists:true,selected_index_count:1,sample_expected_count:0,sample_data_metadata_count:0,indices:[{index:'cycle36-alias',docs_count:1}],embedding:{mapping_available:false,mapping_dimensions:null,vector_count:0,document_count:1,runtime_installed:false}});
    if(url.pathname==='/api/concepts/list') return json({concepts:[{id:'cycle36-ui',name:'Retry recovery'}]});
    if(url.pathname==='/api/corpus/schema') return json({index:'cycle36-alias',fields:[{name:'body',type:'text',searchable:true,filterable:false,nested:false},{name:'status',type:'keyword',searchable:false,filterable:true,nested:false}],warnings:[]});
    if(url.pathname==='/api/concepts/runs') return json({runs:[]});
    if(url.pathname==='/api/concepts/mode-comparison-group') return json(comparison);
    if(url.pathname==='/api/concepts/mode-comparison') return json({query:'saved',metrics:{}});
    if(url.pathname==='/api/concepts/tune') return json({status:'ready',recommendations:[]});
    return json({});
  });
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  page.on('pageerror',e=>pageErrors.push(String(e)));
  await page.goto(process.env.CYCLE37_BASE_URL || 'http://127.0.0.1:18782/');
  await page.waitForFunction(()=>document.querySelector('#server-version')?.textContent.trim()==='v0.23.0');
  await page.waitForFunction(()=>!document.querySelector('#workbench-layout')?.classList.contains('hidden'));
  const initialHint=page.locator('#concept-mode-comparison-group-readiness');
  require(await initialHint.count()===1&&await initialHint.isVisible(),'initial readiness hint is absent before a connection attempt');
  require((await initialHint.innerText()).trim().length>0,'initial readiness hint is empty before a connection attempt');
  await page.evaluate(() => {
    state.connected=true; state.connectedIndex='cycle36-alias'; state.connectedIndexExists=true;
    document.querySelector('#index-name').value='cycle36-alias';
    state.schema=[{name:'body',type:'text',searchable:true,filterable:false,nested:false},{name:'status',type:'keyword',searchable:false,filterable:true,nested:false}];
    const concept={id:'cycle36-ui',name:'Retry recovery',description:'synthetic',aliases:[],related:[],excluded_terms:[],
      corpus:{index:'cycle36-alias',title_field:'',text_fields:['body'],filter_fields:['status']},filters:[{field:'status',value:'Open'}],settings:{mode:'bm25',size:2,candidate_size:10},
      queries:[{id:'q1',query:'<img src=x onerror=alert(1)>',split:'train',information_need:'Retry owner'},{id:'q2',query:'who owns recovery',split:'train',information_need:'retry   OWNER'},{id:'q3',query:'validation',split:'validation',information_need:'different need'}]};
    populateConcept(concept); state.conceptId=concept.id; state.savedConceptSnapshot=JSON.stringify(collectConcept());
    document.querySelector('#saved-concepts').innerHTML='<option value="cycle36-ui">Retry recovery</option>';
    document.querySelector('#saved-concepts').value='cycle36-ui'; document.querySelector('#concept-query-select').value='q1';
    state.preview={conceptId:'cycle36-ui',queryId:'q1'};
    updateModeComparisonGroupAction(); updateModeComparisonAction();
  });
  const button=page.locator('#concept-mode-comparison-group');
  const hint=page.locator('#concept-mode-comparison-group-readiness');
  const liveStatus=page.locator('#concept-mode-comparison-group-status');
  require(await hint.count()===1,'visible group readiness explanation is absent');
  require(await hint.isVisible(),'group readiness explanation is not visible');
  require((await button.getAttribute('aria-describedby')||'').split(/\s+/).includes('concept-mode-comparison-group-readiness'),'group action is not programmatically linked to its visible readiness explanation');
  require(await hint.getAttribute('aria-live')!=='polite','readiness text is a polite live region and may chatter on keystrokes');
  const hintText=async()=> (await hint.innerText()).trim();
  const firstReady=await hintText();
  require(/준비|가능|ready/i.test(firstReady),`connected, saved two-query group is not described as ready: ${firstReady}`);
  require(/2/.test(firstReady),`ready explanation omits the group count: ${firstReady}`);
  require(!/title/i.test(firstReady),'readiness explanation appears to rely on hover/title text');
  require(await button.isEnabled(),'ready saved group compare action is disabled');
  require(!calls.some(c=>c.path==='/api/concepts/mode-comparison-group'),'group compare called before explicit activation');

  // Query selection and group-label changes must recompute the explanation
  // without posting a comparison request. Selecting the singleton validation
  // query gives a deterministic insufficient-group state.
  await page.locator('#concept-query-select').selectOption('q3');
  const singletonHint=await hintText();
  require(singletonHint!==firstReady,'readiness did not update when query selection changed');
  require(/2|두|질의|묶음/i.test(singletonHint)&&/추가|두 개|2개|질의/i.test(singletonHint),`singleton group lacks a concrete next action: ${singletonHint}`);
  require(await button.isDisabled(),'singleton group compare action should use native disabled behavior');
  await page.locator('#concept-query-select').selectOption('');
  const noSelectionHint=await hintText();
  require(/선택|질의/i.test(noSelectionHint)&&/선택/i.test(noSelectionHint),`no-selected-query state lacks a next step: ${noSelectionHint}`);
  require(await button.isDisabled(),'no selected row should disable grouped comparison');

  // A saved concept becomes unsaved as soon as a saved group input changes.
  await page.locator('#concept-query-select').selectOption('q1');
  const statusBeforeTyping=(await liveStatus.innerText()).trim();
  await page.locator('.saved-queries-section > summary').click();
  const secondNeed=page.locator('#concept-queries .concept-query-row').nth(1).locator('.saved-query-information-need');
  await secondNeed.fill('another need');
  const unsavedHint=await hintText();
  require(/저장|save/i.test(unsavedHint),`mutated concept does not explain that it must be saved: ${unsavedHint}`);
  require(/저장/i.test(unsavedHint),`unsaved state has no concrete save action: ${unsavedHint}`);
  require(await button.isDisabled(),'unsaved concept should disable grouped comparison');
  require((await liveStatus.innerText()).trim()===statusBeforeTyping,'typing in group inputs changed the comparison live status');
  require(!calls.some(c=>c.path==='/api/concepts/mode-comparison-group'),'input or selection changes triggered a group comparison request');

  // Restore the original saved data before the disconnect/reconnect lifecycle
  // check so the reconnect tests a previously eligible group.
  await page.evaluate(() => {
    const input=[...document.querySelectorAll('.saved-query-information-need')][1];
    input.value='retry   OWNER'; input.dispatchEvent(new Event('input',{bubbles:true}));
    state.savedConceptSnapshot=JSON.stringify(collectConcept()); updateModeComparisonGroupAction();
  });

  // Disconnected state is directly seedable, so verify it separately.
  await page.evaluate(() => { state.savedConceptSnapshot=JSON.stringify(collectConcept()); setConnected(false); });
  const disconnectedHint=await hintText();
  require(/연결|접속/i.test(disconnectedHint)&&/연결|접속/i.test(disconnectedHint),`disconnected state lacks a connection next step: ${disconnectedHint}`);
  require(await button.isDisabled(),'disconnected group compare action should be disabled');

  // Restore the saved, connected same-need group and verify keyboard use still
  // submits exactly the public anchor identifiers on explicit activation.
  await page.locator('#connect-button').click();
  await page.waitForFunction(()=>state.connected===true&&document.querySelector('#concept-mode-comparison-group-readiness')?.dataset.state==='ready');
  const restoredHint=await hintText();
  require(/준비|가능|ready/i.test(restoredHint)&&/2/.test(restoredHint),`restored group does not return to ready: ${restoredHint}`);
  require(await button.isEnabled(),'restored group compare action remains disabled');
  require(!calls.some(c=>c.path==='/api/concepts/mode-comparison-group'),'state restoration triggered a group comparison request');
  await button.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#concept-mode-comparison-group-status')?.textContent.includes('완료'));
  const groupCalls=calls.filter(c=>c.path==='/api/concepts/mode-comparison-group');
  require(groupCalls.length===1,'keyboard activation did not send exactly one grouped comparison');
  const req=groupCalls[0];
  require(req.method==='POST','group comparison did not use POST');
  require(req.body.concept_id==='cycle36-ui'&&req.body.query_id==='q1','request lacks saved concept and selected anchor query ids');
  require(!('query' in req.body)&&!('information_need' in req.body)&&!('query_ids' in req.body)&&!('filters' in req.body)&&!('size' in req.body),'client supplied caller-controlled group/search overrides');
  const result=page.locator('#concept-mode-comparison-group-results');
  const rendered=await result.innerText();
  require(rendered.includes('Retry owner')&&rendered.includes('q1')&&rendered.includes('q2'),'group label or per-query rows are hidden');
  require(!await result.locator('img').count(),'hostile saved query markup was executed/rendered');
  await page.setViewportSize({width:390,height:844});
  const dims=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,body:document.body.scrollWidth}));
  require(dims.body<=dims.viewport,`group readiness/results overflow mobile viewport: ${JSON.stringify(dims)}`);
  require(await page.locator('#concept-mode-comparison').count()===1,'C34 single-query comparison control disappeared');
  require(await page.locator('#concept-tune').count()===1,'tune control disappeared');
  require(consoleErrors.length===0,`console errors: ${JSON.stringify(consoleErrors)}`);
  require(pageErrors.length===0,`page errors: ${JSON.stringify(pageErrors)}`);
  return {result:'PASS',ready:firstReady,singleton:singletonHint,noSelection:noSelectionHint,unsaved:unsavedHint,disconnected:disconnectedHint,keyboardRequest:req,rendered,dimensions:dims,consoleErrors,pageErrors};
}

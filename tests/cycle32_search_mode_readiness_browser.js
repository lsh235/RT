async page => {
  const calls = [];
  const errors = [];
  const require = (condition, message) => { if (!condition) throw new Error(message); };
  const modelName = 'intfloat/multilingual-e5-small';
  const embeddingByIndex = {
    'cycle32-missing': {mapping_available:false,mapping_dimensions:null,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:0,document_count:10},
    'cycle32-mismatch': {mapping_available:true,mapping_dimensions:768,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:10,document_count:10},
    'cycle32-no-runtime': {mapping_available:true,mapping_dimensions:1024,runtime_installed:false,model_cached:false,model_name:modelName,vector_count:10,document_count:10},
    'cycle32-zero': {mapping_available:true,mapping_dimensions:1024,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:0,document_count:10},
    'cycle32-unknown': {mapping_available:true,mapping_dimensions:1024,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:'unknown',document_count:10},
    'cycle32-partial': {mapping_available:true,mapping_dimensions:1024,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:3,document_count:10},
    'cycle32-uncached': {mapping_available:true,mapping_dimensions:1024,runtime_installed:true,model_cached:false,model_name:modelName,vector_count:10,document_count:10},
    'cycle32-ready': {mapping_available:true,mapping_dimensions:1024,runtime_installed:true,model_cached:true,model_name:modelName,vector_count:10,document_count:10}
  };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const request = route.request();
    let body = {};
    try { body = request.method() === 'POST' ? request.postDataJSON() : {}; } catch {}
    calls.push({path:url.pathname,method:request.method(),body});
    if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.20.0'})});
    if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    if (url.pathname === '/api/connect') {
      const index = body.index || 'cycle32-missing';
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
        cluster_name:'cycle32-synthetic-cluster',version:'8.19.0',selected_index:index,selected_index_exists:true,
        selected_index_count:10,sample_expected_count:25,sample_data_metadata_count:25,
        indices:[{index}],embedding:embeddingByIndex[index] || embeddingByIndex['cycle32-missing']
      })});
    }
    if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
    if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
    if (url.pathname === '/api/corpus/schema') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({index:body.index,fields:[]})});
    if (url.pathname === '/api/concepts/quickstart') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({index:body.index,fields:[],sample_documents:[],suggested_title_field:'',suggested_text_fields:[],suggested_filter_fields:[]})});
    if (url.pathname === '/api/ai/status') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[]})});
    if (url.pathname === '/api/search') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({mode:body.mode,total:0,took_ms:1,query:{synthetic:true},hits:[]})});
    if (url.pathname === '/api/code-rag') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({issues:{hits:[],total:0},code:{code_hits:[],semantic_hits:[],total_code_matches:0},answer:{text:'synthetic'}})});
    if (url.pathname === '/api/vectorize') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message:'synthetic only'})});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  });
  // The CLI owns native modal handling, so shim only the confirm boundary for deterministic cancel/accept assertions.
  await page.addInitScript(() => {
    window.__cycle32ConfirmCalls=[];
    window.__cycle32ConfirmDecision='dismiss';
    window.confirm = message => {
      window.__cycle32ConfirmCalls.push(String(message));
      return window.__cycle32ConfirmDecision === 'accept';
    };
  });
  page.on('console', message => { if (message.type()==='error') errors.push(message.text()); });

  const startupCalls=Promise.all([
    page.waitForResponse(response=>new URL(response.url()).pathname==='/api/codebase-status'),
    page.waitForResponse(response=>new URL(response.url()).pathname==='/api/ai/status')
  ]);
  await page.goto('http://127.0.0.1:18777/');
  await startupCalls;
  await page.waitForFunction(() => document.querySelector('#server-version')?.textContent.trim() === 'v0.20.0');

  async function connectTo(index) {
    await page.evaluate(async indexName => {
      document.querySelector('#index-name').value=indexName;
      await connect();
    },index);
    await page.waitForFunction(indexName => state.connected && !document.querySelector('#connect-button')?.disabled && document.querySelector('#connection-status')?.textContent.includes('연결됨') && document.querySelector('#index-name')?.value===indexName,index);
    await page.waitForTimeout(100); // let routed post-connect refreshes settle before asserting mode changes are network-free
  }
  async function mode(value) {
    const beforeCalls=calls.length;
    const beforeStorage=await page.evaluate(()=>JSON.stringify([...Object.entries(localStorage),...Object.entries(sessionStorage)]));
    await page.locator('#search-mode').selectOption(value);
    require(calls.length===beforeCalls,`changing mode to ${value} made an API request: ${JSON.stringify(calls.slice(beforeCalls))}`);
    require(beforeStorage===await page.evaluate(()=>JSON.stringify([...Object.entries(localStorage),...Object.entries(sessionStorage)])),`changing mode to ${value} wrote persistent state`);
    const helper=page.locator('#search-mode-readiness');
    if (value==='bm25') require(!(await helper.isVisible()),'BM25 readiness helper should be hidden');
    else {
      require(await helper.isVisible(),`${value} readiness helper is not visible`);
      require(await helper.getAttribute('role')==='status'&&await helper.getAttribute('aria-live')==='polite','readiness helper lacks polite status semantics');
    }
  }
  async function assertNoVectorSearch(modeName) {
    const before=calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length;
    await mode(modeName);
    const guidance=await page.locator('#search-mode-readiness').innerText();
    require(!guidance.includes('2.24 GB')&&!guidance.includes('2.24GB'),'known-blocked mode still implies a first-query model download can proceed');
    await page.locator('#search-button').click();
    await page.waitForTimeout(80);
    const after=calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length;
    require(after===before,`${modeName} known-blocked prerequisites sent a search/vectorize request`);
  }
  async function waitForCall(path, predicate, previousCount, label) {
    const deadline=Date.now()+2500;
    while (calls.filter(call=>call.path===path&&predicate(call)).length<=previousCount&&Date.now()<deadline) await page.waitForTimeout(20);
    const diagnostic=await page.evaluate(()=>({mode:document.querySelector('#search-mode')?.value,query:document.querySelector('#search-query')?.value,connected:state.connected,embedding:state.embedding,embeddingIndex:state.embeddingIndex,buttonDisabled:document.querySelector('#search-button')?.disabled,results:document.querySelector('#search-results')?.innerText,toast:document.querySelector('#toast')?.innerText}));
    require(calls.filter(call=>call.path===path&&predicate(call)).length>previousCount,`${label} request was not observed; diag=${JSON.stringify(diagnostic)}; calls=${JSON.stringify(calls.slice(-8))}`);
  }
  async function assertBm25Works(index) {
    await mode('bm25');
    const previous=calls.filter(call=>call.path==='/api/search').length;
    await page.locator('#search-button').click();
    await waitForCall('/api/search',call=>call.body.mode==='bm25',previous,'BM25 search');
    const request=calls.filter(call=>call.path==='/api/search').at(-1);
    require(calls.filter(call=>call.path==='/api/search').length===previous+1,'BM25 did not make exactly one search request');
    require(request.body.index===index&&request.body.query==='cycle32 exact query','BM25 changed exact index/query under readiness state');
  }
  async function snapshot() {
    return page.evaluate(() => ({
      inputs:['#index-name','#search-query','#search-size','#rank-constant','#manual-document-id','#guided-query-text','#concept-name','#concept-query'].map(selector=>[selector,document.querySelector(selector)?.value]),
      mode:document.querySelector('#search-mode').value,
      settings:JSON.stringify(state.conceptSettings),
      filters:JSON.stringify(state.filters),
      lastSearch:JSON.stringify(state.lastSearch),
      resultHtml:document.querySelector('#search-results').innerHTML,
      grade:document.querySelector('#cycle32-grade select')?.value,
      gradeText:document.querySelector('#cycle32-grade')?.textContent,
      storage:[...Object.entries(localStorage),...Object.entries(sessionStorage)]
    }));
  }

  await connectTo('cycle32-missing');
  await page.evaluate(() => {
    document.querySelector('#search-query').value='cycle32 exact query';
    document.querySelector('#search-size').value='20';
    document.querySelector('#rank-constant').value='37';
    document.querySelector('#manual-document-id').value='manual-id-sentinel';
    document.querySelector('#guided-query-text').value='guided-query-sentinel';
    document.querySelector('#concept-name').value='concept-name-sentinel';
    document.querySelector('#concept-query').value='concept-query-sentinel';
    document.querySelector('#concept-preview-results').innerHTML='<div id="cycle32-grade"><select aria-label="saved grade"><option value="2" selected>2</option></select><span>grade-note-sentinel</span></div>';
    document.querySelector('#search-results').innerHTML='<article class="hit-card" data-hit-id="prior-a" data-hit-index="cycle32-missing">prior result A</article><article class="hit-card" data-hit-id="prior-b" data-hit-index="cycle32-missing">prior result B</article>';
    state.lastSearch={index:'cycle32-missing',query:'prior query',mode:'bm25',result:{hits:[{_id:'prior-a'},{_id:'prior-b'}]}};
    state.filters=[{field:'status',value:'Open'}];
  });
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  await page.waitForTimeout(350); // settle tab-triggered and startup background API work before no-request assertions
  const missingReadiness=await page.locator('#search-mode-readiness');
  await mode('vector');
  const missingText=await missingReadiness.innerText();
  require(missingText.includes('rag_embedding')&&missingText.includes('BM25'),`missing mapping guidance is unclear: ${missingText}`);
  require(await page.locator('[data-open-embedding-setup]').isVisible(),'missing mapping has no visible setup shortcut');
  const beforeShortcut=await snapshot();
  const beforeShortcutCalls=calls.length;
  await page.locator('[data-open-embedding-setup]').focus();
  await page.keyboard.press('Enter');
  const setup=page.locator('details.sample-maintenance');
  require(await setup.evaluate(node=>node.open),'setup shortcut did not expand existing embedding details');
  require(await setup.evaluate(node=>node.contains(document.activeElement)),'setup shortcut did not move focus into the existing setup section');
  require(JSON.stringify(beforeShortcut)===JSON.stringify(await snapshot()),'setup shortcut changed search settings/results/grade/storage');
  require(calls.length===beforeShortcutCalls,'setup shortcut made an API request');
  await assertNoVectorSearch('hybrid');
  const hybridBlocked=await missingReadiness.innerText();
  require(hybridBlocked.includes('BM25'),'blocked hybrid state omitted BM25 alternative');
  await assertNoVectorSearch('code_rag');
  const codeBlocked=await missingReadiness.innerText();
  require(codeBlocked.toLowerCase().includes('code')||codeBlocked.includes('코드'),'code_rag readiness explanation missing');
  await assertBm25Works('cycle32-missing');

  await connectTo('cycle32-mismatch');
  for (const modeName of ['vector','hybrid','code_rag']) await assertNoVectorSearch(modeName);
  const mismatchText=await missingReadiness.innerText();
  require(mismatchText.includes('768')&&mismatchText.includes('1024'),'mismatched vector dimensions are not stated');
  await assertBm25Works('cycle32-mismatch');

  await connectTo('cycle32-no-runtime');
  for (const modeName of ['vector','hybrid','code_rag']) await assertNoVectorSearch(modeName);
  require((await missingReadiness.innerText()).includes('FastEmbed'),'missing FastEmbed runtime is not stated');
  await assertBm25Works('cycle32-no-runtime');

  await connectTo('cycle32-zero');
  for (const modeName of ['vector','hybrid','code_rag']) await assertNoVectorSearch(modeName);
  require((await missingReadiness.innerText()).includes('0/10'),'zero vector coverage is not explicit');
  await assertBm25Works('cycle32-zero');

  await connectTo('cycle32-unknown');
  for (const modeName of ['vector','hybrid','code_rag']) await assertNoVectorSearch(modeName);
  require(/확인할 수 없|확인할 수 없습니다/.test(await missingReadiness.innerText()),'unknown vector count is not reported as unknown');
  await assertBm25Works('cycle32-unknown');

  await connectTo('cycle32-partial');
  await mode('hybrid');
  const partialText=await missingReadiness.innerText();
  require(partialText.includes('3/10'),'partial vector N/M coverage is missing');
  require(partialText.includes('벡터')&&partialText.includes('어휘'),'partial hybrid does not explain lexical and vector lanes');
  await mode('code_rag');
  const partialCodeText=await missingReadiness.innerText();
  require(partialCodeText.includes('3/10')&&partialCodeText.includes('Jira')&&partialCodeText.includes('벡터')&&partialCodeText.includes('어휘')&&partialCodeText.includes('코드'),'partial code_rag does not explain vector and lexical Jira paths plus separate code candidates');

  // Exercise the real index-change handler so readiness is rebound to the latest connection.
  await page.locator('#index-name').fill('cycle32-ready');
  const readyConnect=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/connect'&&response.request().postDataJSON()?.index==='cycle32-ready');
  await page.locator('#index-name').dispatchEvent('change');
  await readyConnect;
  await page.waitForFunction(()=>state.connected&&state.embedding?.vector_count===10&&!document.querySelector('#connect-button')?.disabled);
  const readyText=await missingReadiness.innerText();
  require(readyText.includes('10/10'),'ready status does not reflect latest index connection coverage');
  const identityUnknown=/모델/.test(readyText)&&(/알 수 없|확인할 수 없|확인되지|보장하지 않/.test(readyText));
  require(identityUnknown,'ready state implies stored-vector model identity is known');
  require(readyText.includes('cycle32-ready')||/최근|현재 연결/.test(readyText),'ready status is not bounded to the latest connection');
  await mode('vector');
  const cachedDialogs=(await page.evaluate(()=>window.__cycle32ConfirmCalls)).length;
  const cachedVectorCount=calls.filter(call=>call.path==='/api/search'&&call.body.mode==='vector').length;
  const vectorDebug=await page.evaluate(()=>({mode:document.querySelector('#search-mode').value,query:document.querySelector('#search-query').value,connected:state.connected,index:document.querySelector('#index-name').value,embedding:state.embedding,embeddingIndex:state.embeddingIndex,buttonDisabled:document.querySelector('#search-button').disabled,readiness:searchModeReadiness()}));
  require(!vectorDebug.readiness.blocked&&!vectorDebug.readiness.requiresModelDownload&&vectorDebug.embedding.model_cached===true,`cached vector setup unexpectedly blocked or uncached: ${JSON.stringify(vectorDebug)}`);
  await page.evaluate(()=>runSearch());
  await waitForCall('/api/search',call=>call.body.mode==='vector',cachedVectorCount,'cached vector search');
  require((await page.evaluate(()=>window.__cycle32ConfirmCalls)).length===cachedDialogs,'cached local model unexpectedly prompted for first-time download');

  await connectTo('cycle32-uncached');
  await mode('vector');
  const beforeCancel=await snapshot();
  const searchBeforeCancel=calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length;
  const confirmBeforeCancel=(await page.evaluate(()=>window.__cycle32ConfirmCalls)).length;
  await page.evaluate(()=>runSearch());
  await page.waitForTimeout(50);
  const confirmCallsAfterCancel=await page.evaluate(()=>window.__cycle32ConfirmCalls);
  require(confirmCallsAfterCancel.length===confirmBeforeCancel+1,'uncached vector query did not request explicit confirmation');
  const prompt=confirmCallsAfterCancel.at(-1);
  require(prompt.includes('2.24GB')||prompt.includes('2.24 GB'),'confirmation does not name the approximate 2.24 GB first download');
  require(/첫|최초/.test(prompt)&&/다운로드|download/i.test(prompt),'confirmation omits the first-time model download warning');
  require(calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length===searchBeforeCancel,'cancelled vector query made a search/vectorize request');
  require(JSON.stringify(beforeCancel)===JSON.stringify(await snapshot()),'cancelling model download changed inputs/settings/results/grade/storage');

  for (const modeName of ['hybrid','code_rag']) {
    await mode(modeName);
    const before=calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length;
    const confirmsBefore=(await page.evaluate(()=>window.__cycle32ConfirmCalls)).length;
    await page.evaluate(()=>runSearch());
    await page.waitForTimeout(50);
    require((await page.evaluate(()=>window.__cycle32ConfirmCalls)).length===confirmsBefore+1,`${modeName} uncached vector-dependent query did not ask before download`);
    require(calls.filter(call=>call.path==='/api/search'||call.path==='/api/code-rag'||call.path==='/api/vectorize').length===before,`${modeName} canceled query made a search/vectorize request`);
  }

  await mode('vector');
  await page.evaluate(()=>{window.__cycle32ConfirmDecision='accept';});
  const beforeAcceptedSearch=calls.filter(call=>call.path==='/api/search').length;
  const acceptedBefore=calls.filter(call=>call.path==='/api/search'&&call.body.mode==='vector').length;
  await page.evaluate(()=>runSearch());
  await waitForCall('/api/search',call=>call.body.mode==='vector',acceptedBefore,'confirmed vector search');
  const accepted=calls.filter(call=>call.path==='/api/search').at(-1);
  require(accepted.body.mode==='vector'&&accepted.body.query==='cycle32 exact query'&&accepted.body.index==='cycle32-uncached','confirmed vector request did not preserve exact query/index/mode');
  require(calls.filter(call=>call.path==='/api/search').length===beforeAcceptedSearch+1,'accepted vector query did not make exactly one search request');

  const beforeResize=await page.evaluate(()=>({query:document.querySelector('#search-query').value,mode:document.querySelector('#search-mode').value,size:document.querySelector('#search-size').value,rank:document.querySelector('#rank-constant').value}));
  await page.setViewportSize({width:1280,height:900});
  const desktop=await page.evaluate(()=>({vw:document.documentElement.clientWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  require(desktop.doc<=desktop.vw&&desktop.body<=desktop.vw,`1280px horizontal overflow: ${JSON.stringify(desktop)}`);
  await page.setViewportSize({width:390,height:844});
  const mobile=await page.evaluate(()=>({vw:document.documentElement.clientWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  require(mobile.doc<=mobile.vw&&mobile.body<=mobile.vw,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
  const afterResize=await page.evaluate(()=>({query:document.querySelector('#search-query').value,mode:document.querySelector('#search-mode').value,size:document.querySelector('#search-size').value,rank:document.querySelector('#rank-constant').value}));
  require(JSON.stringify(beforeResize)===JSON.stringify(afterResize),'responsive resize changed query/mode/settings');
  require(errors.length===0,`browser console errors: ${JSON.stringify(errors)}`);
  return {
    version:'v0.20.0',
    blockedModes:['vector','hybrid','code_rag'],
    blockedStates:['missing mapping','dimension mismatch','runtime absent','zero vectors','unknown vector count'],
    partial:partialText,
    ready:readyText,
    dialogMessages:await page.evaluate(()=>window.__cycle32ConfirmCalls),
    nativeModalAppearance:'NOT VERIFIED: Playwright CLI auto-handles native dialogs; confirm boundary was deterministically shimmed.' ,
    searchCalls:calls.filter(call=>call.path==='/api/search').map(call=>({mode:call.body.mode,index:call.body.index,query:call.body.query})),
    codeRagCalls:calls.filter(call=>call.path==='/api/code-rag').length,
    vectorizeCalls:calls.filter(call=>call.path==='/api/vectorize').length,
    desktop,mobile,consoleErrors:errors
  };
}

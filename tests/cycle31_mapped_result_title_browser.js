async page => {
  const calls = [];
  const errors = [];
  const require = (condition, message) => { if (!condition) throw new Error(message); };
  const rows = {
    bm25: [
      {_index:'cycle31-generic',_id:'mapped-title',_score:8.1,_source:{title:'Generic mapped title',summary:'Generic Jira fallback'}},
      {_index:'cycle31-generic',_id:'blank-title',_score:7.2,_source:{title:'   ',summary:'Summary fallback for blank title'}},
      {_index:'cycle31-generic',_id:'object-title',_score:6.3,_source:{title:{text:'must not stringify'},summary:'Summary fallback for object'}},
      {_index:'cycle31-generic',_id:'array-title',_score:5.4,_source:{title:['must not stringify'],summary:'Summary fallback for array'}},
      {_index:'cycle31-generic',_id:'xss-title',_score:4.5,_source:{title:'<img src=x onerror="window.__cycle30Xss=true">',summary:'XSS fallback'}},
      {_index:'cycle31-generic',_id:'absent-title',_score:3.6,_source:{summary:'Summary fallback for absent title'}},
      {_index:'cycle31-generic',_id:'nested-title',_score:3.3,_source:{meta:{nested_heading:'must not use nested title'},summary:'Summary fallback for nested field'}},
      {_index:'cycle31-generic',_id:'nonsearchable-title',_score:3.0,_source:{not_searchable:'must not use non-searchable title',summary:'Summary fallback for non-searchable field'}},
      {_index:'cycle31-generic',_id:'absent-all',_score:2.7,_source:{}},
      {_index:'cycle31-generic',_id:'long-title',_score:1.8,_source:{title:'L'.repeat(300),summary:'Long title fallback'}}
    ],
    hybrid: [{_index:'cycle30-hybrid-alias',_id:'hybrid-title',_score:0.037,_source:{title:'Hybrid selected title',summary:'Hybrid display summary'}}],
    vector: [{_index:'cycle30-vector',_id:'vector-title',_score:0.91,_source:{title:'Vector selected title',summary:'Vector display summary'}}]
  };
  await page.addInitScript(() => { window.__cycle30Xss = false; });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const req = route.request();
    let body = {};
    try { if (req.method() === 'POST') body = req.postDataJSON(); } catch {}
    calls.push({path:url.pathname,method:req.method(),body});
    if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.19.0'})});
    if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    if (url.pathname === '/api/search') { const hits=(rows[body.mode]||rows.bm25).map(hit=>body.index==='cycle31-alias'?{...hit,_index:'cycle31-concrete-v1'}:hit); return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({mode:body.mode,total:hits.length,took_ms:2,query:{synthetic:true},hits})}); }
    if (url.pathname === '/api/code-rag') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({issues:{hits:[{_index:'cycle31-generic',_id:'code-rag-title',_score:1,_source:{title:'Do not use mapped title here',summary:'Code RAG summary'}}],total:1},code:{code_hits:[],semantic_hits:[]},answer:{text:'Synthetic answer'}})});
    if (url.pathname === '/api/ai/status') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[{id:'codex',available:false,auth_state:'unavailable',error_code:'unavailable',models:[]}]})});
    if (url.pathname === '/api/ai/sessions/create') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({session_id:'cycle30-session'})});
    if (url.pathname === '/api/ai/sessions/message') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job_id:'cycle30-job'})});
    if (url.pathname === '/api/ai/jobs/get') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'succeeded',result:{text:'synthetic response'}})});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  });
  page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });

  await page.goto('http://127.0.0.1:18776/');
  await page.waitForFunction(() => document.querySelector('#server-version')?.textContent.trim() === 'v0.19.0');
  await page.waitForFunction(() => state.aiProviders.some(item=>item.id==='codex'));
  await page.evaluate(() => {
    state.connected = true;
    document.querySelector('#search-button').disabled = false;
    document.querySelector('#index-name').value = 'cycle31-generic';
    document.querySelector('#search-query').value = 'cycle30 exact search query';
    document.querySelector('#manual-document-id').value = 'manual-id-sentinel';
    document.querySelector('#guided-query-text').value = 'guided-query-sentinel';
    document.querySelector('#concept-name').value = 'concept-name-sentinel';
    document.querySelector('#concept-description').value = 'concept-description-sentinel';
    document.querySelector('#concept-aliases').value = 'alias-sentinel';
    document.querySelector('#concept-exclusions').value = 'exclusion-sentinel';
    document.querySelector('#concept-query').value = 'concept-query-sentinel';
    document.querySelector('#concept-title-field').innerHTML = '<option value="title">title</option><option value="nested_heading">nested_heading</option><option value="not_searchable">not_searchable</option>';
    document.querySelector('#concept-title-field').value = 'title';
    state.schemaIndex = 'cycle31-generic';
    state.schema = [
      {name:'title',type:'text',searchable:true,nested:false,source_field:'title'},
      {name:'nested_heading',type:'text',searchable:true,nested:true,nested_path:'meta',source_field:'meta.nested_heading'},
      {name:'not_searchable',type:'text',searchable:false,nested:false,source_field:'not_searchable'},
      {name:'summary',type:'text',searchable:true,nested:false,source_field:'summary'},
      {name:'status',type:'keyword',searchable:true,nested:false,source_field:'status'}
    ];
    document.querySelector('#concept-text-fields').innerHTML = '<label><input type="checkbox" value="summary" checked><span>summary</span></label>';
    document.querySelector('#concept-filter-fields').innerHTML = '<label><input type="checkbox" value="status" checked><span>status</span></label>';
    document.querySelector('#concept-weight').value = '2.2';
    document.querySelector('#related-weight').value = '0.6';
    document.querySelector('#concept-size').value = '19';
    document.querySelector('#concept-candidate-size').value = '61';
    document.querySelector('#search-size').value = '23';
    document.querySelector('#rank-constant').value = '41';
    state.conceptSettings = {mode:'bm25',concept_weight:2.2,related_weight:0.6,size:19,candidate_size:61,rank_constant:41,field_boosts:{}};
    document.querySelector('#concept-preview-results').innerHTML = '<div id="cycle30-grade"><select aria-label="saved grade"><option value="3" selected>3</option></select><span>grade-note-sentinel</span></div>';
  });

  async function search(mode) {
    await page.locator('[data-tab="search-panel"]').click();
    await page.locator('#search-panel').waitFor({state:'visible'});
    await page.locator('#search-mode').selectOption(mode);
    await page.locator('#search-button').click();
    await page.locator('#search-results .hit-card').first().waitFor({state:'visible'});
  }
  async function snapshot() {
    return page.evaluate(() => ({
      inputs:['#manual-document-id','#guided-query-text','#concept-name','#concept-description','#concept-aliases','#concept-exclusions','#concept-query','#concept-title-field','#concept-weight','#related-weight','#concept-size','#concept-candidate-size','#search-size','#rank-constant','#search-query'].map(s=>[s,document.querySelector(s).value]),
      grade:document.querySelector('#cycle30-grade select')?.value,
      gradeText:document.querySelector('#cycle30-grade')?.textContent,
      settings:JSON.stringify(state.conceptSettings),
      hits:[...document.querySelectorAll('#search-results .hit-card')].map(c=>[c.dataset.hitId,c.dataset.hitIndex,c.querySelector('.score-value')?.textContent.trim()]),
      lastSearch:JSON.stringify(state.lastSearch)
    }));
  }
  async function stage(index, keyboard=false, expectUnavailable=true) {
    const providerState=await page.evaluate(()=>state.aiProviders.find(item=>item.id==='codex')?.available);
    require(providerState===!expectUnavailable,`unexpected synthetic provider availability: ${providerState}`);
    if (expectUnavailable) require((await page.locator('#ai-provider-status').textContent()).includes('사용 불가'),'unavailable provider indicator is not visible');
    const before=await snapshot();
    const card=page.locator('#search-results .hit-card').nth(index);
    const button=card.locator('button[data-stage-ai-result]');
    require(await button.count()===1,`missing stage action for card ${index}`);
    if (keyboard) { await button.focus(); await page.keyboard.press('Enter'); } else await button.click();
    const panel=page.locator('#concept-panel');
    await panel.waitFor({state:'visible'});
    require(await panel.evaluate(e=>e.classList.contains('active')),'staging did not activate AI coach panel');
    const readout=page.locator('#ai-staged-context');
    const title=await readout.locator('dd').first().textContent();
    const status=page.locator('#ai-result-stage-status[role="status"][aria-live="polite"][aria-atomic="true"]');
    require(await status.count()===1,'expected one persistent accessible live status outside the panel');
    const statusBox=await status.boundingBox();
    require(statusBox&&statusBox.width<=1&&statusBox.height<=1,'expected the persistent status to be visually hidden while remaining in the accessibility tree');
    require(await page.locator('#ai-staged-context [role="status"],#ai-staged-context[aria-live]').count()===0,'staged readout duplicates the persistent live region');
    require((await status.textContent()).includes('화면에만 표시')&&(await status.textContent()).includes('AI 요청에는 포함되지 않습니다'),'status does not announce display-only behavior');
    require((await readout.innerText()).includes('제목/요약'),'title/summary label missing from readout');
    require(await page.locator('#ai-message').inputValue() !== undefined,'AI coach input unavailable');
    require(JSON.stringify(before)===JSON.stringify(await snapshot()),'staging changed identity, grade, settings, rankings, or search state');
    const persisted=await page.evaluate(()=>[...Object.values(localStorage),...Object.values(sessionStorage)].join('\n'));
    require(!persisted.includes(title),'display title entered browser persistent/session storage');
    require(calls.filter(c=>c.path==='/api/ai/sessions/create'||c.path==='/api/ai/sessions/message').length===0,'staging alone made an AI session/message request');
    require(!(await page.evaluate(()=>window.__cycle30Xss)),'XSS-shaped title executed');
    return {title, status:await status.textContent(), readout:await readout.innerText(), html:await readout.innerHTML()};
  }
  const results={};
  for (const mode of ['bm25','hybrid','vector']) {
    await search(mode);
    results[mode]=await stage(0,mode==='hybrid');
    await page.locator('button[data-clear-ai-staged-context]').click();
    require(await page.locator('#ai-staged-context .ai-context-card').count()===0,`${mode} clear action did not remove staged context`);
    require((await page.locator('#ai-result-stage-status').textContent())==='','clear action did not clear persistent status');
  }
  await search('bm25');
  const cardTitles=await page.locator('#search-results .hit-title').allTextContents();
  require(cardTitles[0]==='Generic mapped title','ordinary result card did not use selected mapped scalar title');
  require(cardTitles[1]==='Summary fallback for blank title','blank mapped title did not fall back to summary');
  require(cardTitles[2]==='Summary fallback for object'&&cardTitles[3]==='Summary fallback for array','object/array mapped values were not rejected in favor of summary');
  const xssHtml=await page.locator('#search-results .hit-card').nth(4).innerHTML();
  require(cardTitles[4].includes('<img')&&!xssHtml.includes('<img src=x'),'XSS-shaped mapped title was not escaped in result card');
  results.mapped=await stage(0);
  require(results.mapped.title==='Generic mapped title','staged coach readout did not use selected mapped title');
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  results.blank=await stage(1);
  require(results.blank.title==='Summary fallback for blank title','blank mapped title did not use summary fallback in staged readout');
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  results.malformed=await stage(2);
  require(results.malformed.title==='Summary fallback for object','object mapped value was not rejected in staged readout');
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  results.long=await stage(9);
  require(results.long.title.length<=240&&results.long.title.endsWith('…'),`long title was not visibly truncated to <=240 characters: ${results.long.title.length}`);
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  results.xss=await stage(4);
  require(results.xss.title.includes('<img')&&!results.xss.html.includes('<img src=x')&&results.xss.html.includes('&lt;img'),'XSS title was not inert/escaped in readout');
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  results.absent=await stage(8);
  require(results.absent.title==='제목 없음','missing title and summary did not use 제목 없음 fallback');
  await page.locator('button[data-clear-ai-staged-context]').click();
  await page.evaluate(() => { document.querySelector('#index-name').value='cycle31-alias'; state.schemaIndex='cycle31-alias'; document.querySelector('#concept-title-field').value='title'; });
  await search('bm25');
  const aliasTitle=await page.locator('#search-results .hit-title').first().textContent();
  require(aliasTitle.trim()==='Generic mapped title','selected alias mapping was not used for its concrete hit index');
  await page.evaluate(() => { document.querySelector('#index-name').value='cycle31-generic'; state.schemaIndex='cycle31-generic'; });
  await page.evaluate(() => { document.querySelector('#search-mode').innerHTML += '<option value="code_rag">code_rag</option>'; });
  await search('code_rag');
  const codeRagTitle=await page.locator('#search-results .hit-title').first().textContent();
  require(codeRagTitle.trim()==='Code RAG summary','mapped title changed the separate code-RAG issue rendering');
  await page.evaluate(() => { document.querySelector('#search-mode').value='bm25'; });
  await page.evaluate(() => { state.schemaIndex='cycle31-generic'; document.querySelector('#concept-title-field').value='nested_heading'; });
  await search('bm25');
  const nestedTitle=await page.locator('#search-results .hit-title').nth(6).textContent();
  require(nestedTitle.trim()==='Summary fallback for nested field','nested mapped title was not rejected in favor of summary');
  await page.evaluate(() => { document.querySelector('#concept-title-field').value='not_searchable'; });
  await search('bm25');
  const nonsearchableTitle=await page.locator('#search-results .hit-title').nth(7).textContent();
  require(nonsearchableTitle.trim()==='Summary fallback for non-searchable field','non-searchable mapped title was not rejected in favor of summary');
  await page.evaluate(() => { document.querySelector('#concept-title-field').value='title'; state.schemaIndex='cycle31-other-index'; });
  await search('bm25');
  const staleTitle=await page.locator('#search-results .hit-title').first().textContent();
  require(staleTitle.trim()==='Generic Jira fallback','schema from a different index was reused for title rendering');
  await page.evaluate(() => { state.schema=[]; state.schemaIndex=''; });
  await search('bm25');
  const unavailableTitle=await page.locator('#search-results .hit-title').first().textContent();
  require(unavailableTitle.trim()==='Generic Jira fallback','unavailable mapping did not fall back to summary');
  require(calls.every(call=>!call.path.includes('mapping')&&!call.path.includes('schema')),'result rendering requested mapping/schema data per hit');

  // The title is staged in client state for display, but excluded from the POST body.
  await page.evaluate(() => { state.aiProviders=[{id:'codex',available:true,auth_state:'ready',models:['synthetic'],default_model:'synthetic'}]; renderAiProviderStatus(); });
  await search('hybrid');
  const staged=await stage(0,false,false);
  const exactDraft=await page.locator('#ai-message').inputValue();
  await page.waitForFunction(()=>!document.querySelector('#ai-send').disabled);
  await Promise.all([page.waitForResponse(r=>new URL(r.url()).pathname==='/api/ai/sessions/message'),page.locator('#ai-send').click()]);
  const posts=calls.filter(c=>c.path==='/api/ai/sessions/message');
  require(posts.length===1,'explicit Send did not make exactly one message POST');
  const context=posts[0].body.context;
  require(context.query==='cycle30 exact search query','POST query changed');
  require(context.document?.index==='cycle30-hybrid-alias'&&context.document?.id==='hybrid-title','POST document identity changed');
  require(Object.keys(context).sort().join(',')==='concept,document,query','POST did not preserve the existing concept plus query and document context');
  require(!JSON.stringify(posts[0].body).includes(staged.title),'display title leaked into provider POST payload');
  require(posts[0].body.message===exactDraft.trim(),'POST message draft changed');

  const before=await page.evaluate(()=>({hits:[...document.querySelectorAll('#search-results .hit-card')].map(c=>c.dataset.hitId),context:document.querySelector('#ai-staged-context')?.innerText}));
  await page.setViewportSize({width:1280,height:900});
  const desktop=await page.evaluate(()=>({vw:document.documentElement.clientWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  require(desktop.doc<=desktop.vw&&desktop.body<=desktop.vw,`1280px horizontal overflow: ${JSON.stringify(desktop)}`);
  await page.setViewportSize({width:390,height:844});
  const mobile=await page.evaluate(()=>({vw:document.documentElement.clientWidth,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  require(mobile.doc<=mobile.vw&&mobile.body<=mobile.vw,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
  const after=await page.evaluate(()=>({hits:[...document.querySelectorAll('#search-results .hit-card')].map(c=>c.dataset.hitId),context:document.querySelector('#ai-staged-context')?.innerText}));
  require(JSON.stringify(before)===JSON.stringify(after),'responsive resize changed hit order/context');
  require(errors.length===0,`browser console errors: ${JSON.stringify(errors)}`);
  return {version:'v0.19.0',resultTitles:Object.fromEntries(Object.entries(results).map(([key,value])=>[key,value.title])),ordinaryCardTitles:cardTitles,statusRegions:1,providerPosts:posts.length,providerContextKeys:Object.keys(context).sort(),sessionCreateCount:calls.filter(c=>c.path==='/api/ai/sessions/create').length,desktop,mobile,consoleErrors:errors};
}

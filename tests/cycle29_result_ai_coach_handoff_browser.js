async page => {
const calls = [];
const consoleErrors = [];
let providerAvailable = false;
let failNextMessage = false;
const require = (condition, message) => { if (!condition) throw new Error(message); };
const query = '  exact timeout phrase / cycle29  ';
const hitsByMode = {
  bm25: [
    {_index:'',_id:'INC/QA?x=1&y=2#frag "<script>sentinel</script>',_score:7.25,
      _source:{summary:'<img src=x onerror="window.__cycle29Xss=true"> timeout incident',error_signature:'ECONNRESET'}},
    {_index:'explicit-index',_id:'hybrid-safe',_score:2.5,_source:{summary:'Second BM25 result'}},
  ],
  hybrid: [
    {_index:'hybrid-alias',_id:'HYB/one?mode=rrf&part=1',_score:0.0328,
      retrieval_scores:{bm25:18.75,vector:0.8123},_source:{summary:'Hybrid handoff result'}},
  ],
  vector: [
    {_index:'',_id:'VECTOR/only?x=a&y=b#section',_score:0.7444,
      _source:{summary:'Vector-only handoff result'}},
  ],
};

await page.addInitScript(() => {
  window.__cycle29Xss = false;
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.headers.get('x-cycle29-fail') === '1') {
      return {ok:false,status:503,json:()=>response.json()};
    }
    return response;
  };
});
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  const request = route.request();
  let body = {};
  try { body = request.method() === 'POST' ? request.postDataJSON() : {}; } catch {}
  calls.push({path:url.pathname,method:request.method(),body});
  if (url.pathname === '/api/search') {
    const mode = body.mode;
    const hits = hitsByMode[mode] || hitsByMode.bm25;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      mode,total:hits.length,took_ms:4,query:{synthetic:true},hits,
    })});
  }
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.18.0'})});
  if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  if (url.pathname === '/api/ai/status') {
    const provider = providerAvailable
      ? {id:'codex',available:true,auth_state:'ready',models:['synthetic-model'],default_model:'synthetic-model'}
      : {id:'codex',available:false,auth_state:'unavailable',error_code:'unavailable',models:[]};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[provider]})});
  }
  if (url.pathname === '/api/ai/sessions/create') {
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({session_id:'synthetic-session'})});
  }
  if (url.pathname === '/api/ai/sessions/history') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({messages:[]})});
  if (url.pathname === '/api/ai/sessions/message') {
    if (failNextMessage) {
      failNextMessage = false;
      return route.fulfill({status:200,headers:{'x-cycle29-fail':'1'},contentType:'application/json',body:JSON.stringify({error:'synthetic provider failure'})});
    }
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job_id:'synthetic-job'})});
  }
  if (url.pathname === '/api/ai/jobs/get') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({status:'succeeded',result:{text:'synthetic response'}})});
  return route.fulfill({status:200,contentType:'application/json',body:'{}'});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });

await page.goto('http://127.0.0.1:18775/');
await page.waitForFunction(()=>document.querySelector('#server-version')?.textContent.trim()==='v0.18.0');
await page.evaluate(() => {
  state.connected = true;
  document.querySelector('#search-button').disabled = false;
  document.querySelector('#index-name').value = 'selected-index';
  document.querySelector('#search-query').value = '  exact timeout phrase / cycle29  ';
  document.querySelector('#manual-document-id').value = 'MANUAL-ID-SENTINEL';
  document.querySelector('#guided-query-text').value = 'guided query sentinel';
  document.querySelector('#concept-name').value = 'concept name sentinel';
  document.querySelector('#concept-description').value = 'concept description sentinel';
  document.querySelector('#concept-aliases').value = 'alias sentinel';
  document.querySelector('#concept-exclusions').value = 'exclusion sentinel';
  document.querySelector('#concept-query').value = 'concept query sentinel';
  document.querySelector('#concept-title-field').value = 'summary';
  document.querySelector('#concept-text-fields').innerHTML = '<label><input type="checkbox" value="summary" checked><span>summary</span></label>';
  document.querySelector('#concept-filter-fields').innerHTML = '<label><input type="checkbox" value="status" checked><span>status</span></label>';
  document.querySelector('#concept-weight').value = '2.4';
  document.querySelector('#related-weight').value = '0.7';
  document.querySelector('#concept-size').value = '17';
  document.querySelector('#concept-candidate-size').value = '65';
  document.querySelector('#concept-field-boosts').innerHTML = '<label>summary<input class="text-input" data-boost-field="summary" type="number" value="1.6"></label>';
  state.conceptSettings = {mode:'bm25',concept_weight:2.4,related_weight:0.7,size:17,candidate_size:65,rank_constant:60,field_boosts:{summary:1.6}};
  state.conceptFilters = [{field:'status',value:'Open'}];
  renderConceptFilterRows();
  document.querySelector('#concept-queries').replaceChildren();
  addConceptQuery('saved query sentinel alpha','train','cycle29-query-alpha','cycle29 need alpha');
  addConceptQuery('saved query sentinel beta','validation','cycle29-query-beta','cycle29 need beta');
  refreshQueryChoices('cycle29-query-beta');
  document.querySelector('#concept-query').value = 'saved query sentinel beta';
  document.querySelector('#search-size').value = '20';
  document.querySelector('#rank-constant').value = '37';
  document.querySelector('#concept-preview-results').innerHTML = '<div id="cycle29-grade-sentinel"><select aria-label="saved grade"><option value="2" selected>2</option></select><span>saved grade note</span></div>';
});

async function runMode(mode) {
  await page.locator('[data-tab="search-panel"]').click();
  await page.locator('#search-panel').waitFor({state:'visible'});
  await page.locator('#search-mode').selectOption(mode);
  await page.locator('#search-button').click();
  await page.locator('#search-results .hit-card').first().waitFor({state:'visible',timeout:7000});
  return page.evaluate(() => ({
    cards:[...document.querySelectorAll('#search-results .hit-card')].map(card=>({
      id:card.dataset.hitId,index:card.dataset.hitIndex,score:card.querySelector('.score-value')?.textContent.trim(),
      title:card.querySelector('.hit-title')?.textContent.trim(),html:card.innerHTML,
    })),
    query:state.lastSearch?.query,mode:state.lastSearch?.mode||state.lastSearch?.result?.mode,
  }));
}

function handoffButton(card) {
  return card.locator('button[data-stage-ai-result]');
}
function stagedContext() {
  return page.locator('#ai-staged-context');
}
function clearButton() {
  return page.locator('button[data-clear-ai-staged-context]');
}
async function waitNoSessionCalls() {
  await page.waitForTimeout(150);
  const sessionCalls = calls.filter(call=>/^\/api\/ai\/sessions\/(create|message)$/.test(call.path));
  require(sessionCalls.length===0,`handoff unexpectedly created a session or sent a message: ${JSON.stringify(sessionCalls)}`);
}
async function capturePreservedInputs() {
  return page.evaluate(() => ({
    manual:document.querySelector('#manual-document-id').value,
    guided:document.querySelector('#guided-query-text').value,
    conceptName:document.querySelector('#concept-name').value,
    conceptDescription:document.querySelector('#concept-description').value,
    aliases:document.querySelector('#concept-aliases').value,
    exclusions:document.querySelector('#concept-exclusions').value,
    conceptQuery:document.querySelector('#concept-query').value,
    selectedSavedConcept:document.querySelector('#saved-concepts').value,
    selectedSavedQuery:document.querySelector('#concept-query-select').value,
    titleField:document.querySelector('#concept-title-field').value,
    textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(input=>input.value),
    filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(input=>input.value),
    conceptFilters:[...document.querySelectorAll('#concept-filter-rows .concept-filter-row')].map(row=>({field:row.querySelector('.concept-filter-field').value,value:row.querySelector('.concept-filter-value').value})),
    conceptSettings:{weight:document.querySelector('#concept-weight').value,relatedWeight:document.querySelector('#related-weight').value,size:document.querySelector('#concept-size').value,candidateSize:document.querySelector('#concept-candidate-size').value,fieldBoosts:[...document.querySelectorAll('#concept-field-boosts [data-boost-field]')].map(input=>({field:input.dataset.boostField,value:input.value}))},
    savedQueries:[...document.querySelectorAll('#concept-queries .concept-query-row')].map(row=>({id:row.dataset.queryId,text:row.querySelector('.saved-query-text').value,informationNeed:row.querySelector('.saved-query-information-need').value,split:row.querySelector('.saved-query-split').value})),
    searchSettings:{mode:document.querySelector('#search-mode').value,size:document.querySelector('#search-size').value,rankConstant:document.querySelector('#rank-constant').value},
    searchQuery:document.querySelector('#search-query').value,
    grade:document.querySelector('#cycle29-grade-sentinel select')?.value,
    gradeNote:document.querySelector('#cycle29-grade-sentinel')?.textContent,
    cards:[...document.querySelectorAll('#search-results .hit-card')].map(card=>({id:card.dataset.hitId,index:card.dataset.hitIndex,score:card.querySelector('.score-value')?.textContent.trim()})),
    lastSearch:state.lastSearch,
  }));
}
async function stage(mode, index, keyboard=false) {
  const before=await capturePreservedInputs();
  const card=page.locator('#search-results .hit-card').nth(index);
  const action=handoffButton(card);
  require(await action.count()===1,`expected one explicit AI coach handoff action on ${mode} card ${index}; card=${(await card.innerText()).slice(0,500)} html=${(await card.innerHTML()).slice(-1200)}`);
  if (keyboard) {
    await action.focus();
    await page.keyboard.press('Enter');
  } else await action.click();
  await page.locator('#concept-panel').waitFor({state:'visible'});
  const context=stagedContext();
  require(await context.count()===1&&await context.isVisible(),`staged result context is not visibly exposed for ${mode}/${index}`);
  const message=await page.locator('#ai-message').inputValue();
  require(message.trim().length>0,`handoff did not stage an AI message draft for ${mode}/${index}`);
  const after=await capturePreservedInputs();
  require(JSON.stringify(before)===JSON.stringify(after),`handoff changed user inputs, grade, search results/order/scores, or lastSearch for ${mode}/${index}: before=${JSON.stringify(before)} after=${JSON.stringify(after)}`);
  require(await page.locator('#concept-panel').evaluate(el=>el.classList.contains('active')),`handoff did not activate the AI coach tab for ${mode}/${index}`);
  require(!(await page.evaluate(()=>window.__cycle29Xss)),`XSS-shaped result metadata executed during handoff`);
  await waitNoSessionCalls();
  const clear=clearButton();
  require(await clear.count()===1&&await clear.isVisible(),`staged context has no visible clear action for ${mode}/${index}`);
  await clear.click();
  await page.waitForTimeout(50);
  require(!(await context.count())||!(await context.isVisible()),`clear action did not remove the staged result context for ${mode}/${index}`);
  await waitNoSessionCalls();
  return {before, message};
}

const observations=[];
const bm25=await runMode('bm25');
require(bm25.cards.length===2,`synthetic BM25 cards did not render: ${JSON.stringify(bm25.cards)}`);
require(bm25.cards[0].id===hitsByMode.bm25[0]._id,`URL/XSS-shaped BM25 ID was not preserved in the card DOM: ${JSON.stringify(bm25.cards[0])}`);
require(bm25.cards[0].title.includes('onerror')&&!bm25.cards[0].html.includes('<img src=x'),`XSS-shaped metadata was not escaped in the result card: ${bm25.cards[0].html}`);
observations.push(await stage('bm25',0));

const hybrid=await runMode('hybrid');
require(hybrid.cards.length===1&&hybrid.cards[0].index==='hybrid-alias',`hybrid hit did not preserve its exact alias index: ${JSON.stringify(hybrid.cards)}`);
observations.push(await stage('hybrid',0,true));

const vector=await runMode('vector');
require(vector.cards.length===1,`synthetic vector card did not render: ${JSON.stringify(vector.cards)}`);
observations.push(await stage('vector',0));

// With no available provider, handoff and clear remain local UI actions.
await page.evaluate(()=>{state.aiProviders=[{id:'codex',available:false,auth_state:'unavailable',error_code:'unavailable',models:[]}];renderAiProviderStatus();});
await page.locator('[data-tab="search-panel"]').click();
await page.locator('#search-panel').waitFor({state:'visible'});
await stage('vector',0);

// Stage once more, then explicitly send. Only this click may create the session and post the context.
providerAvailable=true;
await page.locator('#ai-refresh-status').click();
await page.waitForFunction(()=>state.aiProviders.some(item=>item.id==='codex'&&item.available));
await page.locator('[data-tab="search-panel"]').click();
await page.locator('#search-panel').waitFor({state:'visible'});
const finalCard=page.locator('#search-results .hit-card').first();
const finalAction=handoffButton(finalCard);
require(await finalAction.count()===1,'final send scenario cannot find the result-card handoff action');
await finalAction.click();
const staged=stagedContext();
require(await staged.isVisible(),'final send scenario did not stage visible result context');
const stagedMessage=await page.locator('#ai-message').inputValue();
require(stagedMessage.trim().length>0,'final send scenario did not create a non-empty message draft');
await waitNoSessionCalls();
failNextMessage = true;
await page.waitForFunction(()=>!document.querySelector('#ai-send').disabled);
await Promise.all([
  page.waitForResponse(response=>new URL(response.url()).pathname==='/api/ai/sessions/create'),
  page.locator('#ai-send').click(),
]);
await page.waitForTimeout(200);
const createCalls=calls.filter(call=>call.path==='/api/ai/sessions/create');
require(createCalls.length===1,`explicit Send should create one session, got ${createCalls.length}: ${JSON.stringify(createCalls)}`);
const firstAttempt=calls.filter(call=>call.path==='/api/ai/sessions/message');
require(firstAttempt.length===1,`explicit Send should post one coach message, got ${firstAttempt.length}: ${JSON.stringify(firstAttempt)}`);
require(firstAttempt[0].body.message===stagedMessage.trim(),`explicit Send did not send the staged message draft: ${JSON.stringify(firstAttempt[0].body)}`);
require(firstAttempt[0].body.context?.query===vector.query?.trim(),`posted coach context query differs from the exact state.lastSearch.query: ${JSON.stringify({expected:vector.query,sent:firstAttempt[0].body.context})}`);
require(firstAttempt[0].body.context?.document?.index==='selected-index'&&firstAttempt[0].body.context?.document?.id===hitsByMode.vector[0]._id,
  `posted coach context lost the selected index or exact URL-sensitive vector document identity: ${JSON.stringify(firstAttempt[0].body.context)}`);
await page.waitForFunction(()=>!document.querySelector('#ai-retry').disabled);
await page.locator('#ai-retry').click();
await page.waitForTimeout(250);
const retryMessageCalls=calls.filter(call=>call.path==='/api/ai/sessions/message');
require(retryMessageCalls.length===2,`retry after failed Send should post one additional coach message, got ${retryMessageCalls.length}: ${JSON.stringify(retryMessageCalls)}`);
require(JSON.stringify(retryMessageCalls[1].body.context)===JSON.stringify(retryMessageCalls[0].body.context),`retry changed the exact context from the failed attempt: ${JSON.stringify(retryMessageCalls)}`);
require(retryMessageCalls[1].body.message===retryMessageCalls[0].body.message,`retry changed the exact message from the failed attempt: ${JSON.stringify(retryMessageCalls)}`);
await page.waitForFunction(()=>!document.querySelector('#ai-send').disabled);
const afterRetry=await page.evaluate(()=>({staged:state.stagedAiResultContext,ordinary:aiContext()}));
require(afterRetry.staged===null,`successful retry left stale staged result context in state: ${JSON.stringify(afterRetry.staged)}`);
require(await page.locator('#ai-staged-context .ai-context-card').count()===0,`successful retry left the staged result readout visible: ${await page.locator('#ai-staged-context').innerText()}`);
require(afterRetry.ordinary.query==='guided query sentinel'&&afterRetry.ordinary.document?.id==='MANUAL-ID-SENTINEL',
  `ordinary AI context after successful retry still uses the previous result query/document instead of the user's current coach inputs: ${JSON.stringify(afterRetry.ordinary)}`);

// Exercise the explicit `_index` path as well as the selected-index fallback above.
await page.locator('[data-tab="search-panel"]').click();
await page.locator('#search-panel').waitFor({state:'visible'});
await page.locator('#search-mode').selectOption('hybrid');
await page.locator('#search-button').click();
await page.locator('#search-results .hit-card').first().waitFor({state:'visible',timeout:7000});
await handoffButton(page.locator('#search-results .hit-card').first()).click();
const aliasContext=stagedContext();
require((await aliasContext.innerText()).includes('hybrid-alias')&&(await aliasContext.innerText()).includes(hitsByMode.hybrid[0]._id),`hybrid alias context display lost the exact index or id: ${await aliasContext.innerText()}`);
await page.waitForFunction(()=>!document.querySelector('#ai-send').disabled);
await Promise.all([
  page.waitForResponse(response=>new URL(response.url()).pathname==='/api/ai/sessions/message'),
  page.locator('#ai-send').click(),
]);
await page.waitForTimeout(200);
const explicitMessageCalls=calls.filter(call=>call.path==='/api/ai/sessions/message');
require(explicitMessageCalls.length===3,`second explicit Send should add one message request, got ${explicitMessageCalls.length}: ${JSON.stringify(explicitMessageCalls)}`);
require(explicitMessageCalls[2].body.context?.document?.index==='hybrid-alias'&&explicitMessageCalls[2].body.context?.document?.id===hitsByMode.hybrid[0]._id,
  `posted coach context lost the explicit alias index or exact URL-sensitive hybrid ID: ${JSON.stringify(explicitMessageCalls[2].body.context)}`);
const sent=retryMessageCalls[0].body;
require(!(await page.evaluate(()=>window.__cycle29Xss)),`XSS-shaped result metadata executed after Send`);

// Leave a staged context visible for the two viewport checks.
await page.waitForFunction(()=>!document.querySelector('#ai-send').disabled);
await page.locator('[data-tab="search-panel"]').click();
await page.locator('#search-panel').waitFor({state:'visible'});
await handoffButton(page.locator('#search-results .hit-card').first()).click();

const beforeResponsive=await page.evaluate(()=>({
  cards:[...document.querySelectorAll('#search-results .hit-card')].map(card=>({id:card.dataset.hitId,index:card.dataset.hitIndex,score:card.querySelector('.score-value')?.textContent.trim()})),
  activePanel:document.querySelector('.tab-panel.active')?.id,
  context:document.querySelector('#ai-staged-context')?.innerText,
}));
await page.setViewportSize({width:1280,height:900});
const desktop=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(desktop.documentWidth<=desktop.width&&desktop.bodyWidth<=desktop.width,`1280px horizontal overflow: ${JSON.stringify(desktop)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
const afterResponsive=await page.evaluate(()=>({
  cards:[...document.querySelectorAll('#search-results .hit-card')].map(card=>({id:card.dataset.hitId,index:card.dataset.hitIndex,score:card.querySelector('.score-value')?.textContent.trim()})),
  activePanel:document.querySelector('.tab-panel.active')?.id,
  context:document.querySelector('#ai-staged-context')?.innerText,
}));
require(JSON.stringify(beforeResponsive)===JSON.stringify(afterResponsive),`responsive viewport change altered visible search results or staged context: ${JSON.stringify({beforeResponsive,afterResponsive})}`);
require(consoleErrors.length===0,`application console errors: ${JSON.stringify(consoleErrors)}`);

return {
  pageVersion:'v0.18.0',
  modes:{bm25:bm25.cards.map(card=>({id:card.id,index:card.index,score:card.score})),hybrid:hybrid.cards.map(card=>({id:card.id,index:card.index,score:card.score})),vector:vector.cards.map(card=>({id:card.id,index:card.index,score:card.score}))},
  stagedContexts:observations.length,
  sessionCreateCount:calls.filter(call=>call.path==='/api/ai/sessions/create').length,
  messages:calls.filter(call=>call.path==='/api/ai/sessions/message').map(call=>({message:call.body.message,context:call.body.context})),
  searchCalls:calls.filter(call=>call.path==='/api/search').map(call=>({mode:call.body.mode,query:call.body.query})),
  aiStatusCalls:calls.filter(call=>call.path==='/api/ai/status').length,
  desktop,mobile,consoleErrors,
};
}

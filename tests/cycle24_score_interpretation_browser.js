async page => {
const apiCalls = [];
const consoleErrors = [];
const hits = mode => [
  {_index:'synthetic-index',_id:`${mode}-first`,_score:mode==='hybrid'?0.0328:7.25,
    retrieval_scores: mode==='hybrid'?{bm25:18.75,vector:0.8123}:undefined,
    _source:{summary:`${mode} first result`,root_cause:'Synthetic cause'}},
  {_index:'synthetic-index',_id:`${mode}-second`,_score:mode==='hybrid'?0.0161:2.5,
    retrieval_scores: mode==='hybrid'?{bm25:3.5,vector:0.4012}:undefined,
    _source:{summary:`${mode} second result`}}
];

await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  const request = route.request();
  const body = request.method() === 'POST' ? request.postDataJSON() : {};
  apiCalls.push({path:url.pathname,method:request.method(),body});
  if (url.pathname === '/api/search') {
    const mode = body.mode;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      mode,total:2,took_ms:4,query:{rank_constant:60,query:{synthetic:true}},hits:hits(mode)
    })});
  }
  if (url.pathname === '/api/code-rag') {
    const issues = hits('hybrid');
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      issues:{mode:'hybrid',total:2,hits:issues},
      code:{code_hits:[],semantic_hits:[],total_code_matches:0,project:'synthetic'},
      answer:{text:'Synthetic evidence only',notice:'Synthetic fixture'}
    })});
  }
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({})});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });
await page.reload();
await page.waitForTimeout(250);
await page.locator('[data-tab="search-panel"]').click();
await page.evaluate(() => {
  state.connected = true;
  document.querySelector('#search-button').disabled = false;
  document.querySelector('#index-name').value = 'synthetic-index';
  document.querySelector('#search-query').value = 'synthetic query';
  document.querySelector('#search-size').value = '5';
});

const require=(condition,message)=>{if(!condition)throw new Error(message);};
const checkMode = async (mode, endpoint, expectedGuidance, forbiddenGuidance=[]) => {
  try {
    await page.locator('#search-mode').selectOption(mode,{timeout:5000});
    await page.locator('#search-button').click({timeout:5000});
    await page.waitForFunction(expected => {
      const summary=document.querySelector('#search-summary');
      const guidance=summary?.querySelector('.score-guidance')?.innerText || '';
      return !summary?.classList.contains('hidden') && guidance.includes(expected);
    },expectedGuidance[0],{timeout:7000});
  } catch (error) {
    const diagnostic=await page.evaluate(()=>({mode:document.querySelector('#search-mode')?.value,
      buttonDisabled:document.querySelector('#search-button')?.disabled,
      summary:document.querySelector('#search-summary')?.innerText,
      results:document.querySelector('#search-results')?.innerText?.slice(0,400)}));
    throw new Error(`${mode}: UI flow timed out ${JSON.stringify(diagnostic)}; ${error.message}`);
  }
  const view = await page.evaluate(() => ({
    summary:document.querySelector('#search-summary').innerText,
    guidance:document.querySelector('#search-summary .score-guidance')?.innerText || '',
    ids:[...document.querySelectorAll('#search-results .hit-card')].map(card=>card.dataset.hitId),
    scores:[...document.querySelectorAll('#search-results .score-value')].map(node=>node.innerText),
    labels:[...document.querySelectorAll('#search-results .score-label')].map(node=>node.innerText),
    components:[...document.querySelectorAll('#search-results .hit-section')].map(node=>node.innerText)
  }));
  require(view.guidance.length>0,`${mode}: no visible summary guidance`);
  for (const text of expectedGuidance) require(view.guidance.includes(text),`${mode}: missing caveat ${text}: ${view.guidance}`);
  for (const text of forbiddenGuidance) require(!view.guidance.includes(text),`${mode}: stale guidance ${text}: ${view.guidance}`);
  require(view.ids.join(',')===`${mode==='code_rag'?'hybrid':mode}-first,${mode==='code_rag'?'hybrid':mode}-second`,`${mode}: rendering changed synthetic hit order ${JSON.stringify(view.ids)}`);
  const expectedScores=mode==='hybrid'||mode==='code_rag'?['0.0328','0.0161']:mode==='bm25'?['7.2500','2.5000']:['7.2500','2.5000'];
  require(view.scores.join(',')===expectedScores.join(','),`${mode}: rendering changed scores ${JSON.stringify(view.scores)}`);
  if (mode==='hybrid'||mode==='code_rag') {
    require(view.labels.every(label=>label.startsWith('RRF SCORE')),`${mode}: RRF labels changed ${JSON.stringify(view.labels)}`);
    require(view.components.some(s=>s.includes('BM25 18.7500')&&s.includes('Vector 0.8123')),
      `${mode}: visible raw component values missing ${JSON.stringify(view.components)}`);
  }
  const call=apiCalls.filter(c=>c.path===endpoint).at(-1);
  require(call?.body?.mode===mode,`${mode}: request mode changed ${JSON.stringify(call)}`);
  require(call?.body?.query==='synthetic query',`${mode}: request query changed ${JSON.stringify(call)}`);
  require(call?.method==='POST',`${mode}: API method changed ${JSON.stringify(call)}`);
  return {mode,guidance:view.guidance,ids:view.ids,scores:view.scores,labels:view.labels};
};

const bm25=await checkMode('bm25','/api/search',['BM25','텍스트 일치','확률','직접 비교할 수 없습니다'],['벡터 점수는','RRF 점수는']);
const vector=await checkMode('vector','/api/search',['벡터 점수','임베딩','유사도','확률','BM25','다른 모델 설정'],['BM25 점수는 이 검색']);
const hybrid=await checkMode('hybrid','/api/search',['RRF 점수','순위','원점수의 합이 아닙니다','척도가 달라 직접 비교할 수 없고','확률'],['BM25 점수는 이 검색','벡터 점수는 선택한']);
const codeRag=await checkMode('code_rag','/api/code-rag',['RRF 점수','순위','원점수의 합이 아닙니다','척도가 달라 직접 비교할 수 없고','확률'],['BM25 점수는 이 검색','벡터 점수는 선택한']);

for (const result of [bm25,vector,hybrid,codeRag]) {
  require(!/\b\d+(?:\.\d+)?\s*%|정확도|정밀도|재현율|품질이 보장|관련성이 높|정답/.test(result.guidance),
    `${result.mode}: guidance implies percentages, accuracy, or retrieval quality: ${result.guidance}`);
}
const expectedCalls=apiCalls.filter(c=>['/api/search','/api/code-rag'].includes(c.path));
require(expectedCalls.map(c=>`${c.path}:${c.body.mode}:${c.body.query}`).join('|')===
  '/api/search:bm25:synthetic query|/api/search:vector:synthetic query|/api/search:hybrid:synthetic query|/api/code-rag:code_rag:synthetic query',
  `rendering/mode changes altered API behavior ${JSON.stringify(expectedCalls)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors after mocked reload ${JSON.stringify(consoleErrors)}`);
console.log(JSON.stringify({bm25,vector,hybrid,codeRag,mobile,apiCalls:expectedCalls,consoleErrors}));
}

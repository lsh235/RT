async page => {
const apiCalls = [];
const consoleErrors = [];
const require=(condition,message)=>{if(!condition)throw new Error(message);};

const bm25Hits = [
  {_index:'synthetic-index',_id:'bm25-highlight',_score:7.25,
    _source:{summary:'Source summary must not replace returned snippets',error_signature:'Source error sentinel'},
    highlight:{
      summary:['Prefix <mark>timeout</mark> suffix','SECOND SUMMARY FRAGMENT MUST NOT APPEAR'],
      error_signature:['<img src=x onerror="window.__xss=true"><script>window.__xss=true</script><mark>ECONNRESET</mark> <mark class="bad">NOT EXACT</mark> & literal '+'x'.repeat(300)+'TAIL-SENTINEL'],
      root_cause:['THIRD ALLOWED FIELD MUST NOT APPEAR'],
      title:['DISALLOWED FIELD MUST NOT APPEAR'],
    }},
  {_index:'synthetic-index',_id:'bm25-no-highlight',_score:2.5,
    _source:{summary:'Legacy card with no returned highlight'}},
];
const hybridHits = [
  {_index:'synthetic-index',_id:'hybrid-bm25-highlight',_score:0.0328,
    retrieval_scores:{bm25:18.75,vector:0.8123},_source:{summary:'Hybrid result with lexical source'},
    highlight:{summary:['Hybrid <mark>timeout</mark> fragment']}},
  {_index:'synthetic-index',_id:'hybrid-vector-only',_score:0.0161,
    retrieval_scores:{bm25:null,vector:0.4012},_source:{summary:'Hybrid vector-only candidate with no lexical excerpt'}},
];
const vectorHits = [
  {_index:'synthetic-index',_id:'vector-only',_score:0.7444,
    _source:{summary:'Vector candidate without lexical highlight'}},
];

await page.addInitScript(() => { window.__xss = false; });
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  const request = route.request();
  let body = {};
  try { body = request.method() === 'POST' ? request.postDataJSON() : {}; } catch {}
  apiCalls.push({path:url.pathname,method:request.method(),body});
  if (url.pathname === '/api/search') {
    const mode=body.mode;
    const hits=mode==='bm25'?bm25Hits:mode==='hybrid'?hybridHits:vectorHits;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      mode,total:hits.length,took_ms:4,query:{synthetic:true},hits,
    })});
  }
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.17.9'})});
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({})});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });

await page.goto('http://127.0.0.1:18775/');
await page.locator('[data-tab="search-panel"]').click();
await page.evaluate(() => {
  state.connected=true;
  document.querySelector('#search-button').disabled=false;
  document.querySelector('#index-name').value='synthetic-index';
  document.querySelector('#search-query').value='timeout ECONNRESET';
  document.querySelector('#search-size').value='10';
  // A separate saved-grade sentinel verifies search rendering does not mutate evaluation state.
  document.querySelector('#concept-preview-results').innerHTML='<div id="cycle28-grade-sentinel"><select aria-label="saved grade"><option value="2" selected>2</option></select><span>saved grade note</span></div>';
});

async function searchMode(mode) {
  await page.locator('#search-mode').selectOption(mode);
  await page.locator('#search-button').click();
  const expectedId=mode==='bm25'?'bm25-highlight':mode==='hybrid'?'hybrid-bm25-highlight':'vector-only';
  await page.locator(`#search-results .hit-card[data-hit-id="${expectedId}"]`).waitFor({state:'visible',timeout:7000});
  return page.evaluate(() => ({
    cards:[...document.querySelectorAll('#search-results .hit-card')].map(card=>({
      id:card.dataset.hitId,
      score:card.querySelector('.score-value')?.textContent.trim(),
      scoreLabel:card.querySelector('.score-label')?.textContent.trim(),
      title:card.querySelector('.hit-title')?.textContent.trim(),
      highlightText:card.querySelector('.result-highlights')?.innerText||'',
      highlightHtml:card.querySelector('.result-highlights')?.innerHTML||'',
      highlightCount:card.querySelectorAll('.result-highlight-fragment').length,
      marks:[...card.querySelectorAll('.result-highlight-fragment mark')].map(mark=>mark.textContent),
      fragmentText:[...card.querySelectorAll('.result-highlight-fragment span')].map(span=>span.textContent),
    })),
    query:document.querySelector('#search-query').value,
    versionLabel:document.querySelector('#server-version')?.textContent.trim(),
    grade:document.querySelector('#cycle28-grade-sentinel select')?.value,
    gradeText:document.querySelector('#cycle28-grade-sentinel')?.innerText,
  }));
}

const bm25=await searchMode('bm25');
require(bm25.cards.length===2,`BM25 result cards did not render: ${JSON.stringify(bm25.cards)}`);
require(bm25.versionLabel==='v0.17.9',`page version label is not v0.17.9: ${bm25.versionLabel}`);
const bm25First=bm25.cards[0];
require(bm25.cards.map(card=>card.score).join(',')==='7.2500,2.5000'&&bm25.cards.every(card=>card.scoreLabel.startsWith('BM25 SCORE')),`highlight rendering changed BM25 scores: ${JSON.stringify(bm25.cards.map(c=>({score:c.score,label:c.scoreLabel})))}`);
require(bm25.query==='timeout ECONNRESET'&&bm25.grade==='2'&&/saved grade note/.test(bm25.gradeText),`BM25 rendering changed query or saved grade state: ${JSON.stringify(bm25)}`);
require(bm25First.highlightText.includes('요약')&&bm25First.highlightText.includes('에러 시그니처'),`BM25 highlights lack the expected allowlisted field labels: ${bm25First.highlightText}`);
require(bm25First.marks.includes('timeout')&&bm25First.marks.includes('ECONNRESET'),`BM25 returned terms are not visibly marked: ${JSON.stringify(bm25First)}`);
require(!bm25First.highlightText.includes('SECOND SUMMARY FRAGMENT')&&!bm25First.highlightText.includes('THIRD ALLOWED FIELD')&&!bm25First.highlightText.includes('DISALLOWED FIELD'),`renderer did not limit output to first fragments of at most two allowlisted fields: ${bm25First.highlightText}`);
require(bm25First.highlightCount===2,`expected at most two displayed field fragments: ${bm25First.highlightCount}`);
require(bm25First.fragmentText.every(text=>text.length<=240),`a displayed fragment exceeds 240 characters: ${bm25First.fragmentText.map(text=>text.length)}`);
require(bm25First.fragmentText[1].length<=240&&!bm25First.fragmentText[1].includes('TAIL-SENTINEL'),`long synthetic fragment was not capped at 240 characters: ${bm25First.fragmentText[1].length}`);
require(bm25First.highlightHtml.includes('&lt;img')&&bm25First.highlightHtml.includes('&lt;script')&&!bm25First.highlightHtml.includes('<img')&&!bm25First.highlightHtml.includes('<script'),`untrusted fragment markup was not escaped: ${bm25First.highlightHtml}`);
require(bm25First.highlightHtml.includes('<mark>ECONNRESET</mark>')&&bm25First.highlightHtml.includes('&lt;mark class="bad"&gt;NOT EXACT')&&!bm25First.highlightHtml.includes('<mark class="bad">'),`only exact mark tags should become markup: ${bm25First.highlightHtml}`);
require(!bm25.cards[1].highlightText.includes('Source summary must not replace returned snippets'),`missing highlight fell back to _source: ${bm25.cards[1].highlightText}`);
require(bm25.cards[1].highlightText.includes('반환된 강조 발췌가 없습니다')&&bm25.cards[1].highlightText.includes('무관하다고 볼 수 없습니다'),`legacy result without highlight lacks neutral fallback: ${bm25.cards[1].highlightText}`);
require(!(await page.evaluate(()=>window.__xss)),`HTML-shaped highlight executed in the page`);

const beforeHybridCalls=apiCalls.length;
const hybrid=await searchMode('hybrid');
require(hybrid.cards.length===2,`hybrid cards did not render: ${JSON.stringify(hybrid.cards)}`);
require(hybrid.cards[0].marks.includes('timeout')&&hybrid.cards[0].highlightText.includes('요약'),`hybrid did not preserve/display the returned BM25 highlight: ${JSON.stringify(hybrid.cards[0])}`);
require(hybrid.cards[1].highlightText.includes('벡터 검색에서 어휘 강조 발췌는 제공되지 않습니다')&&hybrid.cards[1].highlightText.includes('무관하다고 볼 수 없습니다'),`hybrid vector-only result did not get neutral lexical-excerpt-unavailable copy: ${hybrid.cards[1].highlightText}`);
require(hybrid.cards[0].score==='0.0328'&&hybrid.cards[1].score==='0.0161'&&hybrid.cards.every(card=>card.scoreLabel.startsWith('RRF SCORE')),`highlight rendering changed hybrid scores: ${JSON.stringify(hybrid.cards.map(c=>({score:c.score,label:c.scoreLabel})))}`);
require(hybrid.query==='timeout ECONNRESET'&&hybrid.grade==='2'&&/saved grade note/.test(hybrid.gradeText),`hybrid rendering changed query or saved grade state: ${JSON.stringify(hybrid)}`);

const vector=await searchMode('vector');
require(vector.cards.length===1&&vector.cards[0].highlightText.includes('벡터 검색에서 어휘 강조 발췌는 제공되지 않습니다')&&vector.cards[0].highlightText.includes('무관하다고 볼 수 없습니다'),`pure vector mode lacks neutral lexical-excerpt-unavailable note: ${JSON.stringify(vector.cards)}`);
require(vector.cards[0].score==='0.7444'&&vector.cards[0].scoreLabel.startsWith('VECTOR SCORE'),`highlight rendering changed vector score: ${JSON.stringify(vector.cards[0])}`);
require(vector.query==='timeout ECONNRESET'&&vector.grade==='2'&&/saved grade note/.test(vector.gradeText),`vector rendering changed query or saved grade state: ${JSON.stringify(vector)}`);
require(apiCalls.slice(beforeHybridCalls).filter(call=>call.path==='/api/search').length===2,`mode changes caused unexpected API calls: ${JSON.stringify(apiCalls.slice(beforeHybridCalls))}`);
const searchCalls=apiCalls.filter(call=>call.path==='/api/search');
require(searchCalls.length===3&&searchCalls.map(call=>call.body.mode).join(',')==='bm25,hybrid,vector',`search API behavior changed: ${JSON.stringify(searchCalls)}`);
require(searchCalls.every(call=>call.method==='POST'&&call.body.query==='timeout ECONNRESET'),`search request method/query changed: ${JSON.stringify(searchCalls)}`);
require(!apiCalls.some(call=>/save|grade|judgment|delete|update|tune|evaluate/i.test(call.path)),`result rendering called a mutation/evaluation endpoint: ${JSON.stringify(apiCalls)}`);

await page.setViewportSize({width:1280,height:900});
const desktop=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(desktop.documentWidth<=desktop.width&&desktop.bodyWidth<=desktop.width,`1280px horizontal overflow: ${JSON.stringify(desktop)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors: ${JSON.stringify(consoleErrors)}`);

await page.evaluate(value=>{window.__cycle28Result=value;},{bm25,hybrid,vector,desktop,mobile,apiCalls,consoleErrors});
console.log(JSON.stringify({bm25,hybrid,vector,desktop,mobile,apiCalls,consoleErrors}));
}

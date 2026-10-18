async page => {
const apiCalls = [];
const consoleErrors = [];
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  apiCalls.push({path:url.pathname,method:route.request().method()});
  if (url.pathname === '/api/concepts/information-need-preview') {
    const emptyPreview = {baseline:{hits:[],total:0},candidate:{hits:[],total:0},comparison:[]};
    const baselineEmptyPreview = {baseline:{hits:[],total:0},candidate:{hits:[{
      _index:'synthetic-index',_id:'concept-hit',_score:1,rank:1,organic_rank:1,
      source:{title:'Synthetic hit',body:'A candidate from the concept search'},snippet:'A candidate',evidence:[],
      judgment:{rating:null,pinned:false,reason:''}
    }],total:1},comparison:[]};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      information_need:'Synthetic need',split:'train',count:3,status:'complete',failures:[],results:[
        {query_id:'q-empty-1',query:'first phrasing',split:'train',preview:emptyPreview},
        {query_id:'q-empty-2',query:'second phrasing',split:'train',preview:emptyPreview},
        {query_id:'q-baseline-empty',query:'baseline empty',split:'train',preview:baselineEmptyPreview}
      ]
    })});
  }
  if (url.pathname === '/api/concepts/preview') {
    const payload = route.request().postDataJSON();
    const queryId = payload.query_id;
    const preview = queryId === 'q-baseline-empty'
      ? {baseline:{hits:[],total:0},candidate:{hits:[{
          _index:'synthetic-index',_id:'concept-hit',_score:1,rank:1,organic_rank:1,
          source:{title:'Synthetic hit',body:'A candidate from the concept search'},snippet:'A candidate',evidence:[],
          judgment:{rating:null,pinned:false,reason:''}
        }],total:1},comparison:[]}
      : {baseline:{hits:[],total:0},candidate:{hits:[],total:0},comparison:[]};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({query:'synthetic query',...preview})});
  }
  if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
  if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
  if (url.pathname === '/api/concepts/tune/readiness') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
    eligible:false,reason_code:'train_positive_required',scope:'label_readiness_only',counts:{
      training_queries:3,training_graded:0,training_positive:0,training_graded_queries:0,training_positive_queries:0,
      validation_queries:0,validation_graded:0,validation_positive:0,validation_graded_queries:0,validation_positive_queries:0,
      training_information_need_groups:1,training_graded_information_need_groups:0,training_positive_information_need_groups:0,
      validation_information_need_groups:0,validation_graded_information_need_groups:0,validation_positive_information_need_groups:0,stale:0
    }
  })});
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.17.4'})});
  if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  return route.fulfill({status:200,contentType:'application/json',body:'{}'});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });
await page.reload();
await page.waitForTimeout(250);
const require=(condition,message)=>{if(!condition)throw new Error(message);};
await page.evaluate(() => {
  state.schema=[
    {name:'title',type:'text',searchable:true,filterable:false,nested:false},
    {name:'body',type:'text',searchable:true,filterable:false,nested:false},
    {name:'tenant',type:'keyword',searchable:false,filterable:true,nested:false}
  ];
  state.schemaIndex='synthetic-index';
  document.querySelector('#index-name').value='synthetic-index';
  const concept={id:'cycle23-browser',name:'Synthetic concept',description:'fixture',aliases:[],related:[],excluded_terms:[],
    corpus:{index:'synthetic-index',title_field:'title',text_fields:['body'],filter_fields:['tenant']},
    filters:[{field:'tenant',value:'alpha'}],settings:{mode:'bm25',size:5,candidate_size:8,concept_weight:1,related_weight:1,field_boosts:{body:1}},
    queries:[
      {id:'q-empty-1',query:'first phrasing',split:'train',information_need:'Synthetic need'},
      {id:'q-empty-2',query:'second phrasing',split:'train',information_need:'synthetic   need'},
      {id:'q-baseline-empty',query:'baseline empty',split:'train',information_need:'Synthetic need'}
    ]};
  populateConcept(concept);
  state.connected=true; state.conceptId=concept.id;
  const saved=document.querySelector('#saved-concepts');
  saved.innerHTML='<option value="cycle23-browser">Synthetic concept</option>'; saved.value='cycle23-browser';
  const rows=[...document.querySelectorAll('.concept-query-row')]; rows.forEach(row=>{row.dataset.queryEnsured='true';});
  refreshQueryChoices('q-empty-1'); document.querySelector('#concept-query-select').value='q-empty-1';
  document.querySelector('#concept-query').value='';
  state.savedConceptSnapshot=JSON.stringify(collectConcept());
  updateInformationNeedPreviewAction();
});
await page.waitForFunction(()=>!document.querySelector('#tune-readiness').textContent.includes('확인하고 있습니다'));
await page.waitForTimeout(100);
await page.locator('#information-need-preview').click();
await page.waitForFunction(()=>document.querySelector('#concept-preview-status').textContent.startsWith('완료'));
await page.waitForTimeout(100);
const cards=await page.evaluate(()=>[...document.querySelectorAll('.information-need-query-card')].map(card=>({
  queryId:card.dataset.queryId,empty:card.querySelectorAll('.concept-hit').length===0,
  cta:[...card.querySelectorAll('.locate-document-cta')].map(button=>({tag:button.tagName,type:button.type,text:button.textContent})),
  baselineEmpty:card.querySelector('.concept-results-grid .concept-result-column:first-child .compact-empty')!==null
})));
require(cards.length===3,`expected three synthetic information-need cards: ${JSON.stringify(cards)}`);
for(const id of ['q-empty-1','q-empty-2']) {
  const card=cards.find(item=>item.queryId===id);
  require(card?.cta.length===1&&card.cta[0].tag==='BUTTON'&&card.cta[0].type==='button',`empty candidate card lacks one native button CTA (${id}): ${JSON.stringify(card)}`);
  const message=await page.locator(`.information-need-query-card[data-query-id="${id}"] .concept-candidate-empty`).innerText();
  require(message.includes('개념 적용 결과 목록에 표시할 후보가 없습니다')&&!/인덱스에 없|문서가 없습니다/.test(message),`candidate empty copy overstates document absence (${id}): ${message}`);
}
const baselineOnly=cards.find(item=>item.queryId==='q-baseline-empty');
require(baselineOnly?.baselineEmpty&&baselineOnly.empty===false&&baselineOnly.cta.length===0,`empty baseline wrongly triggered recovery CTA or candidate hit lost: ${JSON.stringify(baselineOnly)}`);

const activateCta=async(id,key)=>{
  const cta=page.locator(`.information-need-query-card[data-query-id="${id}"] .locate-document-cta`);
  await cta.focus();
  const before=await page.evaluate(()=>({concept:JSON.stringify(collectConcept()),queryId:document.querySelector('#concept-query-select').value,
    queryText:document.querySelector('#concept-query').value,manualId:document.querySelector('#manual-document-id').value}));
  const apiCount=apiCalls.length;
  await page.keyboard.press(key);
  const active=await page.waitForFunction(()=>document.activeElement?.id==='locate-document-text');
  await active;
  await page.waitForFunction(()=>{const input=document.querySelector('#locate-document-text');const r=input.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;});
  const result=await page.evaluate(()=>({activeId:document.activeElement?.id,visible:document.querySelector('#locate-document-text').getBoundingClientRect().top>=0,
    concept:JSON.stringify(collectConcept()),queryId:document.querySelector('#concept-query-select').value,queryText:document.querySelector('#concept-query').value,
    manualId:document.querySelector('#manual-document-id').value,judgmentButtons:document.querySelectorAll('.save-judgment').length}));
  require(result.activeId==='locate-document-text'&&result.visible,`${key} did not move focus/scroll to lookup input: ${JSON.stringify(result)}`);
  require(apiCalls.length===apiCount,`${key} CTA click made an API request: ${JSON.stringify(apiCalls.slice(apiCount))}`);
  require(result.concept===before.concept&&result.queryId===before.queryId&&result.queryText===before.queryText&&result.manualId===before.manualId,
    `${key} CTA changed concept/query/document fields (before=${JSON.stringify(before)}, after=${JSON.stringify(result)})`);
  require(!apiCalls.slice(apiCount).some(call=>call.path.includes('/judge')),`${key} CTA saved an evaluation judgment`);
};
await activateCta('q-empty-1','Enter');
await page.locator('#information-need-preview').click();
await page.waitForFunction(()=>document.querySelector('#concept-preview-status').textContent.startsWith('완료'));
await page.waitForTimeout(100);
await activateCta('q-empty-2','Space');

await page.evaluate(()=>{document.querySelector('#concept-query-select').value='q-baseline-empty';document.querySelector('#concept-query').value='';});
await page.evaluate(()=>runConceptPreview());
await page.waitForFunction(()=>document.querySelector('#concept-preview-status').textContent.includes('비교 완료'));
const ordinary=await page.evaluate(()=>({baselineHits:document.querySelectorAll('#concept-preview-results .concept-result-column:first-child .concept-hit').length,
  candidateHits:document.querySelectorAll('#concept-preview-results .concept-result-column:nth-child(2) .concept-hit').length,
  cta:document.querySelectorAll('#concept-preview-results .locate-document-cta').length}));
require(ordinary.baselineHits===0&&ordinary.candidateHits===1&&ordinary.cta===0,`nonempty candidate results must not show recovery CTA: ${JSON.stringify(ordinary)}`);

await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors after mocked reload: ${JSON.stringify(consoleErrors)}`);
console.log(JSON.stringify({cards,ordinary,mobile,apiCalls,consoleErrors}));
}

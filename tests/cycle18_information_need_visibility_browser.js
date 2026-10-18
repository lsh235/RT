async page => {
globalThis.cycle18Mode = 'complete';
const consoleErrors = [];
page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204, body:''});
  if (url.pathname.startsWith('/api/')) {
    if (url.pathname === '/api/concepts/information-need-preview') {
      const hits = (entries, candidate=false) => ({hits:entries.map(([index,id,rank,organicRank,pinned=false]) => ({
        _index:index, _id:id, rank, organic_rank:organicRank, _score:1,
        source:{body:`synthetic ${index}/${id}`}, snippet:`synthetic ${index}/${id}`, evidence:[],
        ...(candidate ? {judgment:{rating:null,pinned,reason:''}} : {})
      })), total:entries.length});
      const previews = {
        'q-one': {
          baseline:hits([['idx-a','shared-id',1,null],['idx-a','shared-id',2,null],['idx-a','single-query-only',3,null],['idx-b','shared-id',4,null]]),
          candidate:hits([['idx-a','candidate-shared',2,null,true],['idx-a','pinned-only',null,null,true],['idx-a','organic-shared',1,null,true],['idx-a','organic-shared',3,3,true]],true)
        },
        'q-two': {
          baseline:hits([['idx-a','shared-id',2,null],['idx-b','shared-id',1,null]]),
          candidate:hits([['idx-a','candidate-shared',4,2,false],['idx-a','organic-shared',3,5,false]],true)
        }
      };
      // The cached concept corpus index is the identity fallback for older hits without _index.
      delete previews['q-one'].baseline.hits[0]._index;
      if (globalThis.cycle18Mode === 'all-failed') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({information_need:'Need <script>bad()</script>',split:'train',count:2,status:'failed',results:[],failures:[
        {query_id:'q-one',query:'find <img src=x onerror=bad()>',split:'train',error:'synthetic failure one'},
        {query_id:'q-two',query:'second wording',split:'train',error:'synthetic failure two'}
      ]})});
      const partial = globalThis.cycle18Mode === 'partial';
      if (globalThis.cycle18Mode === 'no-overlap') {
        const noOverlap = ['q-one','q-two'].map((id,i)=>({query_id:id,query:i?'second wording':'find <img src=x onerror=bad()>',split:'train',preview:{
          baseline:hits([['idx-a',`${id}-base`,1,null]]),candidate:hits([['idx-a',`${id}-candidate`,1,1]],true)
        }}));
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({information_need:'Need',split:'train',count:2,status:'complete',results:noOverlap,failures:[]})});
      }
      const results = [{query_id:'q-one',query:'find <img src=x onerror=bad()>',split:'train',preview:previews['q-one']}];
      if (!partial) results.push({query_id:'q-two',query:'second wording',split:'train',preview:previews['q-two']});
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({information_need:'Need <script>bad()</script>',split:'train',count:2,status:partial?'partial':'complete',results,failures:partial?[{query_id:'q-two',query:'second wording',split:'train',error:'synthetic failure two'}]:[]})});
    }
    if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
    if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
    if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'synthetic'})});
    if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  }
  return route.continue();
});
await page.reload();
await page.waitForTimeout(250);
await page.evaluate(() => {
  state.schema = [{name:'body',type:'text',searchable:true,filterable:false,nested:false}];
  state.schemaIndex = 'idx-a';
  document.querySelector('#index-name').value = 'idx-a';
  const fixture = {id:'cycle18-browser',name:'Synthetic concept',description:'Fixture',aliases:[],related:[],excluded_terms:[],
    corpus:{index:'idx-a',title_field:'',text_fields:['body'],filter_fields:[]},filters:[],
    settings:{mode:'bm25',size:5,candidate_size:5,concept_weight:1,related_weight:1,field_boosts:{body:1}},
    queries:[
      {id:'q-one',query:'find <img src=x onerror=bad()>',split:'train',information_need:'Need <script>bad()</script>'},
      {id:'q-two',query:'second wording',split:'train',information_need:'Need <script>bad()</script>'}
    ]};
  populateConcept(fixture);
  const saved=document.querySelector('#saved-concepts'); saved.innerHTML='<option value="cycle18-browser">Synthetic concept</option>'; saved.value='cycle18-browser';
  state.connected=true; state.conceptId=fixture.id; refreshQueryChoices('q-one'); document.querySelector('#concept-query-select').value='q-one';
  state.savedConceptSnapshot=JSON.stringify(collectConcept()); updateInformationNeedPreviewAction();
  window.__cycle18Fixture=fixture;
});
const clickPreview = async () => {
  await page.locator('#information-need-preview').click();
  await page.waitForFunction(() => !document.querySelector('#information-need-preview').disabled && document.querySelector('#concept-preview-status').textContent.length > 0);
};
await clickPreview();
const complete = await page.evaluate(() => {
  const root=document.querySelector('#information-need-visibility-summary');
  const lanes=[...document.querySelectorAll('.information-need-visibility-lane')];
  const byLane=Object.fromEntries(lanes.map(lane=>[lane.dataset.lane,[...lane.querySelectorAll('.information-need-visibility-document')].map(doc=>({index:doc.dataset.index,id:doc.dataset.id,text:doc.textContent,queryCount:doc.querySelector('.information-need-visibility-query-count')?.textContent||'',occurrences:[...doc.querySelectorAll('.information-need-visibility-occurrence')].map(o=>({queryId:o.dataset.queryId,rank:o.dataset.rank,text:o.textContent}))}))]));
  const gradeIds=[...document.querySelectorAll('.information-need-query-card .judge-controls')].map(x=>x.dataset.queryId);
  return {root:root?.innerText||'',byLane,gradeIds,images:document.querySelectorAll('#concept-preview-results img').length,scriptNodes:document.querySelectorAll('#concept-preview-results script').length,summaryHtml:root?.innerHTML||'',status:document.querySelector('#concept-preview-status').textContent};
});
const require = (condition,message) => { if (!condition) throw new Error(message); };
require(complete.root.includes('successful') || complete.root.includes('성공'),`summary lacks successful-preview evidence boundary: ${complete.root}`);
require(complete.byLane.baseline.length===2,`baseline exact identity/dedup/repeated-only mismatch: ${JSON.stringify(complete.byLane.baseline)}`);
require(complete.byLane.baseline.some(d=>d.index==='idx-a'&&d.id==='shared-id') && complete.byLane.baseline.some(d=>d.index==='idx-b'&&d.id==='shared-id'),`same _id across indices was merged: ${JSON.stringify(complete.byLane.baseline)}`);
require(!complete.byLane.baseline.some(d=>d.id==='single-query-only'),`single-query document unexpectedly appeared`);
const baseA=complete.byLane.baseline.find(d=>d.index==='idx-a'&&d.id==='shared-id');
require(baseA.occurrences.length===2 && baseA.occurrences.some(o=>o.queryId==='q-one'&&o.rank==='1') && baseA.occurrences.some(o=>o.queryId==='q-two'&&o.rank==='2'),`baseline occurrences not distinct-query/exact-rank: ${JSON.stringify(baseA)}`);
require(baseA.queryCount==='2개 질의에서 관찰',`observed-query count mismatch: ${JSON.stringify(baseA)}`);
require(baseA.occurrences.find(o=>o.queryId==='q-one')?.text.includes('find <img src=x onerror=bad()>') && baseA.occurrences.find(o=>o.queryId==='q-one')?.text.includes('q-one'),`original query text/ID not retained in occurrence: ${JSON.stringify(baseA)}`);
require(!complete.byLane.candidate.some(d=>d.id==='candidate-shared') && !complete.byLane.candidate.some(d=>d.id==='pinned-only'),`null-organic pinned documents must not count as visibility: ${JSON.stringify(complete.byLane.candidate)}`);
const organic=complete.byLane.candidate.find(d=>d.id==='organic-shared');
require(organic && organic.occurrences.length===2 && organic.occurrences.some(o=>o.queryId==='q-one'&&o.rank==='3') && organic.occurrences.some(o=>o.queryId==='q-two'&&o.rank==='5'),`same-query null pin then organic hit must contribute exactly one occurrence with organic ranks: ${JSON.stringify(organic)}`);
require(complete.gradeIds.includes('q-one')&&complete.gradeIds.includes('q-two'),`query-specific grading IDs changed: ${JSON.stringify(complete.gradeIds)}`);
require(complete.images===0&&complete.scriptNodes===0&&!complete.summaryHtml.includes('<script>bad'),`hostile text was interpreted as markup: ${complete.summaryHtml}`);
globalThis.cycle18Mode='partial'; await clickPreview();
const partial=await page.evaluate(()=>({text:document.querySelector('#information-need-visibility-summary')?.innerText||'',lanes:[...document.querySelectorAll('.information-need-visibility-lane')].map(x=>x.dataset.lane),status:document.querySelector('#concept-preview-status').textContent,failures:document.querySelectorAll('.notice-error').length}));
require(partial.text.includes('성공한 1개') && (partial.text.includes('unobserved')||partial.text.includes('관측되지')||partial.text.includes('관찰되지')),`partial denominator/unobserved wording missing: ${JSON.stringify(partial)}`);
require(partial.status.includes('부분 완료')&&partial.failures===1,`partial group status mismatch ${JSON.stringify(partial)}`);
globalThis.cycle18Mode='no-overlap'; await clickPreview();
const noOverlap=await page.evaluate(()=>({text:document.querySelector('#information-need-visibility-summary')?.innerText||'',docs:document.querySelectorAll('.information-need-visibility-document').length}));
require(noOverlap.docs===0&&(/no overlapping|no document appeared in multiple|겹치는 문서가 없습니다|여러 질의에 나타난 문서가 없습니다|여러 질의에 반복된 문서가 없습니다/i.test(noOverlap.text)),`no-overlap message missing: ${JSON.stringify(noOverlap)}`);
require(!/no relevant|관련 문서가 없습니다\./i.test(noOverlap.text),`no-overlap wording implies no relevance: ${JSON.stringify(noOverlap.text)}`);
globalThis.cycle18Mode='all-failed'; await clickPreview();
const failed=await page.evaluate(()=>({text:document.querySelector('#information-need-visibility-summary')?.innerText||'',docs:document.querySelectorAll('.information-need-visibility-document').length,status:document.querySelector('#concept-preview-status').textContent,errors:document.querySelectorAll('.notice-error').length}));
require(failed.text.includes('no successful')||failed.text.includes('성공한 질의 결과가 없어'),`all-failed summary must say there is no successful data to summarize: ${JSON.stringify(failed)}`);
require(failed.docs===0&&!/no repeated|no relevant|반복 문서가 없습니다|관련 문서가 없습니다\./i.test(failed.text),`all-failed summary falsely asserts absence: ${JSON.stringify(failed)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth}));
require(mobile.scrollWidth<=mobile.width,`mobile horizontal overflow ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors: ${JSON.stringify(consoleErrors)}`);
console.log(JSON.stringify({complete,partial,noOverlap,failed,mobile,consoleErrors}));
}

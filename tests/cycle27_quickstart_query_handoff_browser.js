async page => {
const apiCalls = [];
const consoleErrors = [];
let activeSampleCount = 3;
const sampleSets = {
  0: [],
  unusable: [{_index:'synthetic-index',_id:'empty-1',source:{title:'   ',summary:{text:'not a scalar'}}}],
  usable: [{_index:'synthetic-index',_id:'usable-1',source:{title:'Usable title',summary:'Usable body'}}],
  3: [
    {_index:'synthetic-index',_id:'sample-1',source:{title:'First title',summary:'First body'}},
    {_index:'synthetic-index',_id:'sample-2',source:{title:'Second title',summary:'Second body'}},
    {_index:'synthetic-index',_id:'sample-3',source:{title:'Third title',summary:`Third body <img src=x onerror="window.__xss=true"> ${'x'.repeat(650)}`}},
  ],
};
const require=(condition,message)=>{if(!condition)throw new Error(message);};

await page.addInitScript(() => { window.__xss = false; });
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  const request = route.request();
  let body = {};
  try { body = request.method() === 'POST' ? request.postDataJSON() : {}; } catch {}
  apiCalls.push({path:url.pathname,method:request.method(),body});
  if (url.pathname === '/api/concepts/quickstart') {
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      index:'synthetic-index',
      fields:[
        {name:'title',type:'text',searchable:true,source_field:'title'},
        {name:'summary',type:'text',searchable:true,source_field:'summary'},
        {name:'tags',type:'keyword',searchable:true,source_field:'tags'},
      ],
      suggested_title_field:'title',suggested_text_fields:['summary'],suggested_filter_fields:['tags'],
      sample_documents:sampleSets[activeSampleCount],
    })});
  }
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.17.8'})});
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({})});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });

async function loadCase(count) {
  activeSampleCount=count;
  await page.goto(`http://127.0.0.1:18775/?samples=${count}`);
  await page.evaluate(() => {
    state.connected=true;
    document.querySelector('#quickstart-fields').disabled=false;
    document.querySelector('#index-name').value='synthetic-index';
    state.schema=[
      {name:'title',type:'text',searchable:true,source_field:'title'},
      {name:'summary',type:'text',searchable:true,source_field:'summary'},
      {name:'tags',type:'keyword',searchable:true,source_field:'tags'},
    ];
    state.schemaIndex='synthetic-index';
    renderSchemaChoices({title_field:'title',text_fields:['summary'],filter_fields:['tags']});
    const guided=document.querySelector('#guided-query-text'); guided.value='existing guided query';
    const conceptQuery=document.querySelector('#concept-query'); if(conceptQuery) conceptQuery.value='saved concept query sentinel';
    const querySelect=document.querySelector('#concept-query-select'); if(querySelect) {
      const option=document.createElement('option'); option.value='synthetic-query-id'; option.textContent='synthetic saved query'; querySelect.append(option); querySelect.value='synthetic-query-id';
    }
    document.querySelector('#concept-preview-results').innerHTML='<div class="cycle27-grade-sentinel"><select aria-label="synthetic grade"><option value="2" selected>2</option></select><span>saved grade sentinel</span></div>';
  });
  await page.locator('#quickstart-fields').click();
  await page.waitForFunction(() => !!document.querySelector('#quickstart-preview')?.dataset.suggestions, null, {timeout:7000});
  await page.waitForFunction(() => document.querySelector('#server-version')?.textContent.trim()==='v0.17.8', null, {timeout:7000});
  await page.waitForTimeout(100);
}

await loadCase(0);
const zero=await page.evaluate(()=>({text:document.querySelector('#quickstart-preview').innerText,actions:document.querySelectorAll('.quickstart-query-handoff').length}));
require(zero.actions===0,`zero samples exposed a handoff action: ${JSON.stringify(zero)}`);

await loadCase('unusable');
const empty=await page.evaluate(()=>({text:document.querySelector('#quickstart-preview').innerText,actions:document.querySelectorAll('.quickstart-query-handoff').length}));
require(empty.actions===0,`sample with no usable scalar text exposed a handoff action: ${JSON.stringify(empty)}`);

await loadCase('usable');
const singleUsable=await page.evaluate(()=>({
  picker:!!document.querySelector('#quickstart-sample-select'),
  actions:document.querySelectorAll('.quickstart-query-handoff').length,
  phrase:document.querySelector('.quickstart-query-handoff')?.getAttribute('data-starter-phrase'),
  title:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  guided:document.querySelector('#guided-query-text').value,
  conceptQuery:document.querySelector('#concept-query')?.value,
  querySelect:document.querySelector('#concept-query-select')?.value,
  grade:document.querySelector('.cycle27-grade-sentinel select')?.value,
  gradeText:document.querySelector('.cycle27-grade-sentinel')?.innerText,
}));
require(!singleUsable.picker&&singleUsable.actions===1&&singleUsable.phrase==='Usable title Usable body',`single usable sample did not expose the no-picker handoff action: ${JSON.stringify(singleUsable)}`);
const beforeSingleClickCalls=apiCalls.length;
await page.locator('.quickstart-query-handoff').click();
const singleUsableAfter=await page.evaluate(()=>({
  guided:document.querySelector('#guided-query-text').value,
  focused:document.activeElement?.id==='guided-query-text',
  title:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  conceptQuery:document.querySelector('#concept-query')?.value,
  querySelect:document.querySelector('#concept-query-select')?.value,
  grade:document.querySelector('.cycle27-grade-sentinel select')?.value,
  gradeText:document.querySelector('.cycle27-grade-sentinel')?.innerText,
}));
require(singleUsableAfter.guided===singleUsable.phrase&&singleUsableAfter.focused,`single usable sample did not populate/focus the guided query: ${JSON.stringify(singleUsableAfter)}`);
require(singleUsableAfter.title===singleUsable.title&&JSON.stringify(singleUsableAfter.textFields)===JSON.stringify(singleUsable.textFields)&&JSON.stringify(singleUsableAfter.filters)===JSON.stringify(singleUsable.filters),`single-sample handoff changed selected fields: ${JSON.stringify(singleUsableAfter)}`);
require(singleUsableAfter.conceptQuery===singleUsable.conceptQuery&&singleUsableAfter.querySelect===singleUsable.querySelect&&singleUsableAfter.grade===singleUsable.grade&&singleUsableAfter.gradeText===singleUsable.gradeText,`single-sample handoff changed query or grade state: ${JSON.stringify(singleUsableAfter)}`);
require(apiCalls.length===beforeSingleClickCalls,`single-sample handoff made an API request: ${JSON.stringify(apiCalls.slice(beforeSingleClickCalls))}`);

await loadCase(3);
const initial=await page.evaluate(()=>({
  count:document.querySelectorAll('.quickstart-query-handoff').length,
  label:document.querySelector('.quickstart-query-handoff')?.textContent.trim(),
  accessibleName:document.querySelector('.quickstart-query-handoff')?.getAttribute('aria-label'),
  title:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  guided:document.querySelector('#guided-query-text').value,
  conceptQuery:document.querySelector('#concept-query')?.value,
  querySelect:document.querySelector('#concept-query-select')?.value,
  grade:document.querySelector('.cycle27-grade-sentinel select')?.value,
  gradeText:document.querySelector('.cycle27-grade-sentinel')?.innerText,
  applyLabel:document.querySelector('#guided-first-preview')?.textContent.trim(),
  versionLabel:document.querySelector('#server-version')?.textContent.trim(),
}));
require(initial.versionLabel==='v0.17.8',`page version label is not v0.17.8: ${initial.versionLabel}`);
require(initial.count===1,`expected one handoff action for selected sample: ${JSON.stringify(initial)}`);
require(/검색 시작 문구로 옮기기/.test(initial.label||initial.accessibleName||''),`handoff action is not labelled clearly: ${JSON.stringify(initial)}`);
require(initial.title==='title'&&initial.textFields.includes('summary')&&initial.filters.includes('tags'),`fixture did not seed selected fields: ${JSON.stringify(initial)}`);
require(initial.guided==='existing guided query'&&initial.conceptQuery==='saved concept query sentinel'&&initial.querySelect==='synthetic-query-id'&&initial.grade==='2'&&/saved grade sentinel/.test(initial.gradeText),`fixture did not seed existing query/grade state: ${JSON.stringify(initial)}`);

// Selection is changed first; the later click must use the currently displayed sample.
await page.locator('#quickstart-sample-select').selectOption('1');
const selectedSecond=await page.evaluate(()=>({
  panel:document.querySelector('#quickstart-sample-panel').innerText,
  button:document.querySelector('.quickstart-query-handoff')?.getAttribute('data-starter-phrase'),
}));
require(selectedSecond.panel.includes('sample-2')&&selectedSecond.button==='Second title Second body',`second sample did not produce its deterministic phrase: ${JSON.stringify(selectedSecond)}`);
const beforeClickCalls=apiCalls.length;
await page.locator('.quickstart-query-handoff').click();
const afterClick=await page.evaluate(()=>({
  guided:document.querySelector('#guided-query-text').value,
  focused:document.activeElement?.id==='guided-query-text',
  title:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  conceptQuery:document.querySelector('#concept-query')?.value,
  querySelect:document.querySelector('#concept-query-select')?.value,
  grade:document.querySelector('.cycle27-grade-sentinel select')?.value,
  gradeText:document.querySelector('.cycle27-grade-sentinel')?.innerText,
  searchButtonLabel:document.querySelector('#guided-first-preview')?.textContent.trim(),
  previewText:document.querySelector('#concept-preview-results')?.innerText,
  sampleButtonCount:document.querySelectorAll('.quickstart-query-handoff').length,
}));
require(afterClick.guided==='Second title Second body',`handoff did not use currently selected sample: ${JSON.stringify(afterClick)}`);
require(afterClick.focused,`handoff did not focus guided query input`);
require(afterClick.title===initial.title&&JSON.stringify(afterClick.textFields)===JSON.stringify(initial.textFields)&&JSON.stringify(afterClick.filters)===JSON.stringify(initial.filters),`handoff changed field selections: ${JSON.stringify(afterClick)}`);
require(afterClick.conceptQuery===initial.conceptQuery&&afterClick.querySelect===initial.querySelect&&afterClick.grade===initial.grade&&afterClick.gradeText===initial.gradeText,`handoff changed existing query or grade state: ${JSON.stringify(afterClick)}`);
require(afterClick.sampleButtonCount===1&&/이 내용으로 결과 보기/.test(afterClick.searchButtonLabel),`explicit search action became unavailable or handoff changed preview state: ${JSON.stringify(afterClick)}`);
require(apiCalls.length===beforeClickCalls,`handoff made an API request: ${JSON.stringify(apiCalls.slice(beforeClickCalls))}`);

await page.locator('#quickstart-sample-select').selectOption('2');
const third=await page.evaluate(()=>({
  phrase:document.querySelector('.quickstart-query-handoff')?.getAttribute('data-starter-phrase')||'',
  source:document.querySelector('#quickstart-sample-panel').textContent,
  html:document.querySelector('#quickstart-sample-panel').innerHTML,
  panel:document.querySelector('#quickstart-sample-panel').innerText,
  injected:window.__xss||!!document.querySelector('#quickstart-sample-panel img'),
}));
require(third.phrase.length>0&&third.phrase.length<=500,`starter phrase is empty or longer than 500 characters: ${third.phrase.length}`);
require(third.source.includes('<img src=x onerror="window.__xss=true">')&&!third.html.includes('<img src=x')&&third.html.includes('&lt;img src=x onerror=&quot;window.__xss=true&quot;&gt;'),`HTML-shaped sample was not escaped as text: ${JSON.stringify(third)}`);
require(!third.injected,`HTML-shaped sample executed in the page`);
const beforeThirdCalls=apiCalls.length;
await page.locator('.quickstart-query-handoff').click();
const thirdHandoff=await page.locator('#guided-query-text').inputValue();
require(thirdHandoff===third.phrase&&thirdHandoff.length<=500,`third sample handoff differed from its bounded plain-text phrase`);
require(apiCalls.length===beforeThirdCalls,`third sample handoff made an API request: ${JSON.stringify(apiCalls.slice(beforeThirdCalls))}`);

const keyboard=await page.evaluate(()=>{const button=document.querySelector('.quickstart-query-handoff');return {tag:button?.tagName,type:button?.type,tabIndex:button?.tabIndex,label:button?.textContent.trim()};});
require(keyboard.tag==='BUTTON'&&keyboard.type==='button'&&keyboard.tabIndex!==-1,`handoff action is not keyboard accessible: ${JSON.stringify(keyboard)}`);
await page.locator('.quickstart-query-handoff').focus();
const beforeKeyboardCalls=apiCalls.length;
await page.keyboard.press('Enter');
require(await page.locator('#guided-query-text').inputValue()===third.phrase,`keyboard activation did not hand off current sample`);
require(apiCalls.length===beforeKeyboardCalls,`keyboard handoff made an API request`);

const apiCallCount=apiCalls.length;
await page.setViewportSize({width:1280,height:900});
const desktop=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(desktop.documentWidth<=desktop.width&&desktop.bodyWidth<=desktop.width,`desktop horizontal overflow ${JSON.stringify(desktop)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow ${JSON.stringify(mobile)}`);
require(apiCalls.length===apiCallCount,`resizing made an API request`);
require(consoleErrors.length===0,`application console errors: ${JSON.stringify(consoleErrors)}`);

const result={zero,empty,singleUsable,singleUsableAfter,initial,selectedSecond,afterClick,third,thirdHandoff,desktop,mobile,apiCalls,consoleErrors};
await page.evaluate(value=>{window.__cycle27Result=value;},result);
console.log(JSON.stringify(result));
}

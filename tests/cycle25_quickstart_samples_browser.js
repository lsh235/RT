async page => {
const apiCalls = [];
const consoleErrors = [];
let activeSampleCount = 3;
const samples = (count) => [
  {_index:'synthetic-index',_id:'sample-1',source:{title:'First title',summary:'First body'}},
  {_index:'synthetic-index',_id:'sample-2',source:{summary:['Second body','array-a','array-b'],tags:['array-a','array-b'],nested:{text:'Second nested body'}}},
  {_index:'synthetic-index',_id:'sample-3',source:{title:'Third title',summary:`Long body <img onerror="window.__xss=true"> ${'x'.repeat(600)}`}},
].slice(0,count);
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
        {name:'nested.text',type:'text',searchable:true,source_field:'nested.text'},
      ],
      suggested_title_field:'title',suggested_text_fields:['summary','nested.text'],
      suggested_filter_fields:['tags'],sample_documents:samples(activeSampleCount),
    })});
  }
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({})});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });

async function loadCase(count) {
  activeSampleCount = count;
  await page.goto(`http://127.0.0.1:18775/?samples=${count}`);
  await page.evaluate(() => {
    state.connected = true;
    document.querySelector('#quickstart-fields').disabled = false;
    document.querySelector('#index-name').value = 'synthetic-index';
  });
  await page.locator('#quickstart-fields').click();
  await page.waitForFunction(() => document.querySelector('#quickstart-preview .quickstart-sample-panel, #quickstart-preview #quickstart-sample-panel, #quickstart-preview .quickstart-sample') !== null, null, {timeout:7000});
  await page.waitForTimeout(100);
}

await loadCase(0);
const zero = await page.evaluate(() => ({
  text:document.querySelector('#quickstart-preview').innerText,
  picker:!!document.querySelector('#quickstart-sample-select'),
  panel:document.querySelector('#quickstart-preview .quickstart-sample')?.innerText || '',
}));
require(!zero.picker && /예시 문서가 없습니다/.test(zero.text),`zero samples did not show graceful empty state: ${JSON.stringify(zero)}`);

await loadCase(1);
const one = await page.evaluate(() => ({
  picker:!!document.querySelector('#quickstart-sample-select'),
  panel:document.querySelector('#quickstart-sample-panel')?.innerText || '',
}));
require(!one.picker && one.panel.includes('sample-1') && one.panel.includes('First title'),`one sample rendering/picker state failed: ${JSON.stringify(one)}`);

await loadCase(3);
const initial = await page.evaluate(() => ({
  options:[...document.querySelectorAll('#quickstart-sample-select option')].map(o=>({value:o.value,text:o.textContent})),
  selected:document.querySelector('#quickstart-sample-select')?.value,
  panel:document.querySelector('#quickstart-sample-panel')?.innerText || '',
  titleField:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  caveat:document.querySelector('.quickstart-sample-caveat')?.innerText || '',
  labelAssociated:!!Array.from(document.querySelector('#quickstart-sample-select')?.labels || []).some(label => label.htmlFor==='quickstart-sample-select' && label.textContent.includes('예시 문서 선택')),
}));
require(initial.options.length===3 && initial.selected==='0',`three-sample picker options/default failed: ${JSON.stringify(initial)}`);
require(initial.panel.includes('sample-1') && initial.panel.includes('First title'),`sample 1 did not render: ${initial.panel}`);
require(/예시/.test(initial.options[0].text) && /sample-1/.test(initial.options[0].text),`picker is not labelled with sample identity: ${JSON.stringify(initial.options)}`);
require(initial.labelAssociated,`native sample picker is not associated with its visible label`);
require(/예시일 뿐|몇 개의 예시/.test(initial.caveat),`sample caveat missing: ${initial.caveat}`);

// Seed unrelated editor and saved-grade state synthetically to prove sample browsing is read-only.
await page.evaluate(() => {
  const query = document.querySelector('#concept-query'); if (query) query.value='synthetic concept query';
  const gradeHost = document.querySelector('#concept-preview-results');
  gradeHost.innerHTML='<div class="synthetic-saved-grade"><select aria-label="synthetic saved grade"><option value="0">0</option><option value="2" selected>2</option></select><span>saved synthetic grade</span></div>';
});
const before = await page.evaluate(() => ({
  titleField:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  query:document.querySelector('#concept-query')?.value,
  grade:document.querySelector('.synthetic-saved-grade select')?.value,
}));
const apiCountBeforeSwitch = apiCalls.length;
await page.locator('#quickstart-sample-select').press('ArrowDown');
await page.waitForFunction(() => document.querySelector('#quickstart-sample-select')?.value==='1' && document.querySelector('#quickstart-sample-panel')?.innerText.includes('sample-2'));
const keyboardDown = await page.evaluate(() => ({selected:document.querySelector('#quickstart-sample-select').value,panel:document.querySelector('#quickstart-sample-panel').innerText}));
require(keyboardDown.selected==='1' && keyboardDown.panel.includes('sample-2'),`ArrowDown did not select and display sample 2: ${JSON.stringify(keyboardDown)}`);
await page.locator('#quickstart-sample-select').press('ArrowUp');
await page.waitForFunction(() => document.querySelector('#quickstart-sample-select')?.value==='0' && document.querySelector('#quickstart-sample-panel')?.innerText.includes('sample-1'));
const keyboardUp = await page.evaluate(() => ({selected:document.querySelector('#quickstart-sample-select').value,panel:document.querySelector('#quickstart-sample-panel').innerText}));
require(keyboardUp.selected==='0' && keyboardUp.panel.includes('sample-1'),`ArrowUp did not select and display sample 1: ${JSON.stringify(keyboardUp)}`);
const afterKeyboard = await page.evaluate(() => ({
  titleField:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  query:document.querySelector('#concept-query')?.value,
  grade:document.querySelector('.synthetic-saved-grade select')?.value,
}));
require(JSON.stringify(before)===JSON.stringify(afterKeyboard),`keyboard switching mutated editor/query/saved grade state: before=${JSON.stringify(before)} after=${JSON.stringify(afterKeyboard)}`);
require(apiCalls.length===apiCountBeforeSwitch,`keyboard switching made API requests: ${JSON.stringify(apiCalls.slice(apiCountBeforeSwitch))}`);
await page.locator('#quickstart-sample-select').selectOption('1');
const second = await page.locator('#quickstart-sample-panel').innerText();
require(second.includes('sample-2') && second.includes('Second body'),`sample 2 did not update ID/body or flatten an array value: ${second}`);
await page.locator('#quickstart-sample-select').selectOption('2');
const third = await page.locator('#quickstart-sample-panel').innerText();
require(third.includes('sample-3') && third.includes('Third title'),`sample 3 did not update title/ID: ${third}`);
require(third.includes('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),`long body value was not readable: ${third.slice(0,600)}`);
const xCount = (third.match(/x/g) || []).length;
require(xCount > 100 && xCount <= 420,`long body preview was not readable within its 420-character bound: ${xCount}`);
const after = await page.evaluate(() => ({
  titleField:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  query:document.querySelector('#concept-query')?.value,
  grade:document.querySelector('.synthetic-saved-grade select')?.value,
  injected:window.__xss || !!document.querySelector('#quickstart-sample-panel img'),
  visibleText:document.querySelector('#quickstart-sample-panel').innerText,
  sourceText:document.querySelector('#quickstart-sample-panel').textContent,
  html:document.querySelector('#quickstart-sample-panel').innerHTML,
}));
const stateAfter = {titleField:after.titleField,textFields:after.textFields,filterFields:after.filterFields,query:after.query,grade:after.grade};
require(JSON.stringify(before)===JSON.stringify(stateAfter),`switching mutated editor/query/saved grade state: before=${JSON.stringify(before)} after=${JSON.stringify(stateAfter)}`);
require(!after.injected && after.sourceText.includes('<img onerror="window.__xss=true">'),`HTML-shaped source was not safely displayed as text: ${JSON.stringify(after)}`);
require(after.html.includes('&lt;img onerror=') && !after.html.includes('<img'),`unsafe source markup was not escaped in panel HTML: ${after.html}`);
require(apiCalls.length===apiCountBeforeSwitch,`sample switching made API requests: ${JSON.stringify(apiCalls.slice(apiCountBeforeSwitch))}`);
const beforeApply = apiCalls.length;
await page.locator('#apply-quickstart-fields').click();
const applied = await page.evaluate(() => ({
  titleField:document.querySelector('#concept-title-field')?.value,
  textFields:[...document.querySelectorAll('#concept-text-fields input:checked')].map(x=>x.value),
  filterFields:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(x=>x.value),
  confirmation:document.querySelector('.selected-field-confirmation')?.innerText || '',
}));
require(applied.titleField==='title' && applied.textFields.includes('summary') && applied.filterFields.includes('tags'),`explicit apply action did not apply suggestions: ${JSON.stringify(applied)}`);
require(apiCalls.length===beforeApply,`explicit field apply made an unexpected API request: ${JSON.stringify(apiCalls.slice(beforeApply))}`);

await page.setViewportSize({width:1280,height:900});
const desktop=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(desktop.documentWidth<=desktop.width&&desktop.bodyWidth<=desktop.width,`desktop horizontal overflow ${JSON.stringify(desktop)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors after mocked interactions ${JSON.stringify(consoleErrors)}`);
const result={zero,one,initial,keyboardDown,keyboardUp,second,third,before,after,applied,desktop,mobile,apiCalls,consoleErrors};
await page.evaluate(value => { window.__cycle25Result=value; },result);
console.log(JSON.stringify(result));
}

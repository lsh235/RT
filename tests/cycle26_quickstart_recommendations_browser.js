async page => {
const apiCalls = [];
const consoleErrors = [];
let activeCase='standard';
const require=(condition,message)=>{if(!condition)throw new Error(message);};

const cases = {
  standard: {
    fields:[
      {name:'title',type:'text',searchable:true,source_field:'title'},
      {name:'summary',type:'text',searchable:true,source_field:'summary'},
      {name:'tags',type:'keyword',searchable:true,source_field:'tags'},
      {name:'created_at',type:'date',searchable:true,source_field:'created_at'},
      {name:'xss_<img src=x onerror=window.__xss=true>',type:'keyword',searchable:true,source_field:'xss_value'},
    ],
    suggested_title_field:'title',suggested_text_fields:['summary'],suggested_filter_fields:['tags'],
  },
  nested: {
    fields:[
      {name:'name',type:'text',searchable:true,source_field:'name'},
      {name:'comments.title',type:'text',searchable:true,nested_path:'comments',source_field:'comments.title'},
      {name:'content',type:'text',searchable:true,source_field:'content'},
      {name:'labels',type:'keyword',searchable:true,source_field:'labels'},
    ],
    suggested_title_field:'name',suggested_text_fields:['content'],suggested_filter_fields:['labels'],
  },
  keyword_only: {
    fields:[
      {name:'name',type:'keyword',searchable:true,source_field:'name'},
      {name:'summary',type:'keyword',searchable:true,source_field:'summary'},
      {name:'status',type:'keyword',searchable:true,source_field:'status'},
    ],
    suggested_title_field:'name',suggested_text_fields:['name','summary'],suggested_filter_fields:['status'],
  },
};

await page.addInitScript(() => { window.__xss = false; });
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  const request = route.request();
  apiCalls.push({path:url.pathname,method:request.method()});
  if (url.pathname === '/api/concepts/quickstart') {
    const fixture = cases[activeCase] || cases.standard;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      index:'synthetic-index',...fixture,
      sample_documents:[{_index:'synthetic-index',_id:'synthetic-1',source:{title:'Synthetic title',name:'Synthetic name',summary:'Synthetic summary',content:'Synthetic content'}}],
    })});
  }
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({})});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });

async function openCase(caseName) {
  activeCase=caseName;
  await page.goto(`http://127.0.0.1:18775/?case=${caseName}`);
  await page.evaluate(({caseName,cases}) => {
    state.connected = true;
    document.querySelector('#quickstart-fields').disabled = false;
    document.querySelector('#index-name').value = 'synthetic-index';
    state.schema = cases[caseName].fields;
    state.schemaIndex = 'synthetic-index';
    renderSchemaChoices({
      title_field: caseName === 'nested' ? 'name' : cases[caseName].fields[0].name,
      text_fields: cases[caseName].fields.filter(field => field.type === 'text').slice(0,1).map(field => field.name),
      filter_fields:[],
    });
    const query=document.querySelector('#concept-query'); if (query) query.value='synthetic preserved query';
    const grade=document.querySelector('#concept-preview-results');
    if (grade) grade.innerHTML='<div class="cycle26-synthetic-grade"><select aria-label="synthetic grade"><option value="1" selected>1</option></select><span>synthetic grade sentinel</span></div>';
  },{caseName,cases});
  await page.locator('#quickstart-fields').click();
  await page.waitForFunction(() => !!document.querySelector('#quickstart-preview')?.dataset.suggestions, null, {timeout:7000});
  for (const summary of await page.locator('#quickstart-preview details > summary').all()) await summary.click();
  await page.waitForTimeout(100);
}

await openCase('standard');
const standard = await page.evaluate(() => ({
  text:document.querySelector('#quickstart-preview').innerText,
  html:document.querySelector('#quickstart-preview').innerHTML,
  title:document.querySelector('#concept-title-field').value,
  body:[...document.querySelectorAll('#concept-text-fields input:checked')].map(input=>input.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(input=>input.value),
  query:document.querySelector('#concept-query')?.value,
  grade:document.querySelector('.cycle26-synthetic-grade select')?.value,
}));
const standardText=standard.text.toLowerCase();
require(/text|match_only_text/.test(standardText),`standard guidance does not identify text-like mapping types: ${standard.text}`);
require(/우선|먼저|priority|prefer/.test(standardText),`standard guidance does not explain text-like body priority: ${standard.text}`);
require(/fallback|대체|그 외|다른 검색 가능|검색 가능한 필드/.test(standardText),`standard guidance does not explain the broader body-field fallback: ${standard.text}`);
require(/keyword/.test(standardText),`standard guidance or mapping labels omit keyword type: ${standard.text}`);
require(/full.?text|전문 검색|전문.*검색/.test(standardText),`guidance does not distinguish keyword candidates from full-text fields: ${standard.text}`);
require(/다르|동일하지|같지|아니|not equivalent|not the same/.test(standardText),`guidance does not state keyword fallback is not equivalent to full-text search: ${standard.text}`);
require(/휴리스틱|heuristic|앱의 매핑 .*규칙에 따른 후보/.test(standardText),`guidance does not label recommendations as app heuristics: ${standard.text}`);
require(/의미.*적합|의미에 맞|semantic.*suitability|semantic fit/.test(standardText),`guidance does not disclaim semantic suitability: ${standard.text}`);
require(/전체 인덱스|index-wide|coverage|전체.*필드/.test(standardText),`guidance does not disclaim index-wide field coverage: ${standard.text}`);
require(standard.text.includes('title')&&standard.text.includes('summary')&&standard.text.includes('tags'),`standard recommendation or mapping type labels omit relevant fields: ${standard.text}`);
require(standard.text.includes('xss_<img src=x onerror=window.__xss=true>')&&!standard.html.includes('<img src=x')&&standard.html.includes('&lt;img src=x onerror=window.__xss=true&gt;'),`field name was not safely escaped: ${standard.html}`);
require(!/true/.test(await page.evaluate(()=>String(window.__xss))),`field name markup executed in the browser`);
require(standard.title==='title'&&standard.body[0]==='title'&&!standard.filters.includes('tags'),`quickstart mutated selected fields before explicit apply: ${JSON.stringify(standard)}`);
require(standard.query==='synthetic preserved query'&&standard.grade==='1',`quickstart mutated query or grade sentinel before explicit apply: ${JSON.stringify(standard)}`);

const beforeApplyCalls=apiCalls.length;
await page.locator('#apply-quickstart-fields').click();
const appliedStandard=await page.evaluate(()=>({
  title:document.querySelector('#concept-title-field').value,
  body:[...document.querySelectorAll('#concept-text-fields input:checked')].map(input=>input.value),
  filters:[...document.querySelectorAll('#concept-filter-fields input:checked')].map(input=>input.value),
  confirmation:document.querySelector('.selected-field-confirmation')?.innerText||'',
}));
require(appliedStandard.title==='title'&&appliedStandard.body.includes('summary')&&appliedStandard.filters.includes('tags'),`explicit Apply failed to apply backend canonical title/body/filter fields: ${JSON.stringify(appliedStandard)}`);
require(apiCalls.length===beforeApplyCalls,`explicit Apply unexpectedly called API: ${JSON.stringify(apiCalls.slice(beforeApplyCalls))}`);

await openCase('nested');
const nested=await page.evaluate(()=>({
  suggested:JSON.parse(document.querySelector('#quickstart-preview').dataset.suggestions||'{}').title_field,
  title:document.querySelector('#concept-title-field').value,
  text:document.querySelector('#quickstart-preview').innerText,
}));
require(nested.suggested==='name'&&nested.title==='name',`nested field overrode backend scalar title suggestion: ${JSON.stringify(nested)}`);
require(/제목 후보:\s*name(?:\s|$)/.test(nested.text),`nested comments.title was promoted in title recommendation summary: ${nested.text}`);
await page.locator('#apply-quickstart-fields').click();
const nestedApplied=await page.locator('#concept-title-field').inputValue();
require(nestedApplied==='name',`explicit Apply did not preserve backend suggested scalar title: ${nestedApplied}`);

await openCase('keyword_only');
const keywordOnly=await page.evaluate(()=>({
  text:document.querySelector('#quickstart-preview').innerText,
  title:document.querySelector('#concept-title-field').value,
  body:[...document.querySelectorAll('#concept-text-fields input:checked')].map(input=>input.value),
}));
const keywordText=keywordOnly.text.toLowerCase();
require(/fallback|대체|그 외|다른 검색 가능|검색 가능한 필드/.test(keywordText),`keyword-only mapping did not identify broader fallback: ${keywordOnly.text}`);
require(/keyword/.test(keywordText),`keyword-only mapping type labels are not visible: ${keywordOnly.text}`);
require(/full.?text|전문 검색|전문.*검색/.test(keywordText)&&/다르|동일하지|같지|아니|not equivalent|not the same/.test(keywordText),`keyword-only fallback is described as equivalent to full-text search: ${keywordOnly.text}`);
require(/휴리스틱|heuristic|앱의 매핑 .*규칙에 따른 후보/.test(keywordText)&&/의미.*적합|의미에 맞|semantic.*suitability|semantic fit/.test(keywordText)&&/전체 인덱스|index-wide|coverage|전체.*필드/.test(keywordText),`keyword-only guidance misses one or more recommendation caveats: ${keywordOnly.text}`);

// Every API route, including bootstrap and AI status, was fulfilled by this synthetic fixture.
require(apiCalls.filter(call=>call.path==='/api/concepts/quickstart').length===3,`expected exactly three synthetic quickstart reads: ${JSON.stringify(apiCalls)}`);
const forbiddenMutations=new Set(['/api/connect','/api/concepts/save','/api/concepts/preview','/api/concepts/judge','/api/concepts/tune','/api/concepts/diagnose','/api/search','/api/evaluate','/api/document','/api/sample-import']);
const unexpectedCalls=apiCalls.filter(call=>forbiddenMutations.has(call.path));
require(unexpectedCalls.length===0,`quickstart/apply caused unexpected API calls: ${JSON.stringify(unexpectedCalls)}`);
require(consoleErrors.length===0,`application console errors with synthetic routes: ${JSON.stringify(consoleErrors)}`);
await page.setViewportSize({width:1280,height:900});
const desktop=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(desktop.documentWidth<=desktop.width&&desktop.bodyWidth<=desktop.width,`desktop horizontal overflow ${JSON.stringify(desktop)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow ${JSON.stringify(mobile)}`);
await page.evaluate(result=>{window.__cycle26Result=result;},{standard,appliedStandard,nested,nestedApplied,keywordOnly,desktop,mobile,apiCalls,consoleErrors});
console.log(JSON.stringify({standard,appliedStandard,nested,nestedApplied,keywordOnly,desktop,mobile,apiCalls,consoleErrors}));
}

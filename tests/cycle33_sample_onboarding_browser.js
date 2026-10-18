async page => {
  const apiCalls = [];
  const consoleErrors = [];
  const pageErrors = [];
  let selected = {index:'cycle33-missing', exists:false, count:0};
  const confirmCalls = [];
  let confirmDecision = 'cancel';
  const require = (condition, message) => { if (!condition) throw new Error(message); };
  const storage = () => JSON.stringify({local:Object.entries(localStorage),session:Object.entries(sessionStorage)});

  await page.addInitScript(() => {
    window.__cycle33ConfirmCalls=[];
    window.__cycle33ConfirmDecision='cancel';
    window.confirm=message => {
      window.__cycle33ConfirmCalls.push(String(message));
      return window.__cycle33ConfirmDecision==='accept';
    };
  });
  await page.route('**/*', async route => {
    const url=new URL(route.request().url());
    if(url.pathname==='/favicon.ico') return route.fulfill({status:204,body:''});
    if(!url.pathname.startsWith('/api/')) return route.continue();
    const request=route.request();
    let body={};
    try { if(request.method()==='POST') body=request.postDataJSON(); } catch {}
    apiCalls.push({path:url.pathname,method:request.method(),body});
    if(url.pathname==='/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.21.0'})});
    if(url.pathname==='/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
    if(url.pathname==='/api/ai/status') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[]})});
    if(url.pathname==='/api/connect') {
      const index=body.index||selected.index;
      if(index==='cycle33-failed') return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic offline endpoint'})});
      const current=index===selected.index?selected:{index,exists:index==='cycle33-empty'||index==='cycle33-full',count:index==='cycle33-full'?4:0};
      selected=current;
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
        cluster_name:'synthetic-cluster',version:'8.19.0',selected_index:index,selected_index_exists:current.exists,
        selected_index_count:current.count,sample_expected_count:25,sample_data_metadata_count:25,
        indices:current.exists?[{index}]:[],embedding:{mapping_available:false,mapping_dimensions:null,runtime_installed:true,model_cached:true,model_name:'synthetic-model',vector_count:0,document_count:current.count}
      })});
    }
    if(url.pathname==='/api/sample-import') {
      selected={index:'cycle33-missing',exists:true,count:25};
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({created:true,index:selected.index,document_count:25,message:'synthetic sample loaded'})});
    }
    if(url.pathname==='/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
    if(url.pathname==='/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
    if(url.pathname==='/api/corpus/schema') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({index:body.index,fields:[]})});
    if(url.pathname==='/api/concepts/quickstart') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({index:body.index,fields:[],sample_documents:[],suggested_title_field:'',suggested_text_fields:[],suggested_filter_fields:[]})});
    return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  });
  page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('503 (Service Unavailable)'))consoleErrors.push(message.text());});
  page.on('pageerror',error=>pageErrors.push(String(error)));

  await page.goto('http://127.0.0.1:18779/');
  await page.waitForFunction(()=>document.querySelector('#server-version')?.textContent.trim()==='v0.21.0');
  const cta=page.locator('#sample-onboarding');
  const openButton=page.locator('#sample-onboarding-open');
  const details=page.locator('details.sample-maintenance');
  const loadButton=page.locator('#load-sample-button');

  async function connectTo(index, exists, count) {
    selected={index,exists,count};
    await page.evaluate(async name=>{document.querySelector('#index-name').value=name;await connect();},index);
    await page.waitForTimeout(200);
    const isVisible=await cta.isVisible();
    if(!exists) require(isVisible,`missing-index CTA hidden for ${index}`);
    else require(!isVisible,`CTA visible for existing index ${index}`);
    require((await page.locator('#connection-status').innerText()).includes('연결됨'),`connect state not established for ${index}`);
  }

  await connectTo('cycle33-missing',false,0);
  const missingCopy=await page.locator('#sample-onboarding-copy').innerText();
  require(missingCopy.includes('cycle33-missing')&&missingCopy.includes('25'),'CTA omits selected index or expected sample count');
  require(!(await details.evaluate(element=>element.open)),'sample details should initially remain collapsed');
  const beforeRequests=apiCalls.length;
  const beforeStorage=await page.evaluate(storage);
  await openButton.focus();
  await page.keyboard.press('Enter');
  require(await details.evaluate(element=>element.open),'keyboard CTA activation did not open the existing disclosure');
  require(await loadButton.evaluate(element=>element===document.activeElement),'CTA did not move focus to the existing sample button');
  require(apiCalls.length===beforeRequests,'CTA activation sent an API request');
  require(beforeStorage===await page.evaluate(storage),'CTA activation wrote local/session storage');

  const prompt='새 인덱스 cycle33-missing를 만들고 테스트용 gRPC 이슈를 적재할까요?\n기존 인덱스는 덮어쓰지 않습니다.';
  const beforeCancel=apiCalls.filter(call=>call.path==='/api/sample-import').length;
  await loadButton.click();
  const confirmsAfterCancel=await page.evaluate(()=>window.__cycle33ConfirmCalls);
  require(confirmsAfterCancel.at(-1)===prompt,`sample-import confirmation changed: ${JSON.stringify(confirmsAfterCancel.at(-1))}`);
  require(apiCalls.filter(call=>call.path==='/api/sample-import').length===beforeCancel,'cancelled confirmation sent sample-import');

  await page.evaluate(()=>{window.__cycle33ConfirmDecision='accept';});
  await loadButton.click();
  const deadline=Date.now()+3000;
  while(apiCalls.filter(call=>call.path==='/api/sample-import').length<1&&Date.now()<deadline) await page.waitForTimeout(20);
  require(apiCalls.filter(call=>call.path==='/api/sample-import').length===1,'accepted confirmation did not send exactly one sample-import request');
  await page.waitForTimeout(300);
  require(!(await cta.isVisible()),'CTA remains visible after selected index becomes populated');

  await connectTo('cycle33-empty',true,0);
  await connectTo('cycle33-full',true,4);
  await page.evaluate(async()=>{document.querySelector('#es-url').value='http://synthetic-unreachable';document.querySelector('#es-url').dispatchEvent(new Event('change',{bubbles:true}));});
  await page.evaluate(async()=>{document.querySelector('#index-name').value='cycle33-failed';await connect();});
  await page.waitForTimeout(100);
  require(!(await cta.isVisible()),'CTA visible after failed/disconnected connection');
  require((await page.locator('#connection-status').innerText()).includes('연결 실패'),'failed connection state was not surfaced');

  await connectTo('cycle33-missing',false,0);
  await page.setViewportSize({width:390,height:844});
  const mobile=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,body:document.body.scrollWidth,cta:document.querySelector('#sample-onboarding').getBoundingClientRect().toJSON(),button:document.querySelector('#sample-onboarding-open').getBoundingClientRect().toJSON(),visible:getComputedStyle(document.querySelector('#sample-onboarding')).display!=='none'}));
  require(mobile.visible&&mobile.body<=mobile.viewport,`mobile CTA is hidden or causes horizontal overflow: ${JSON.stringify(mobile)}`);
  require(mobile.button.width>=280&&mobile.button.height>=36,`mobile CTA button is too small: ${JSON.stringify(mobile.button)}`);
  require(consoleErrors.length===0,`browser console errors: ${JSON.stringify(consoleErrors)}`);
  require(pageErrors.length===0,`browser page errors: ${JSON.stringify(pageErrors)}`);

  return {result:'PASS',missingCopy,apiCalls:apiCalls.map(call=>call.path),confirmCalls:await page.evaluate(()=>window.__cycle33ConfirmCalls),mobile,consoleErrors,pageErrors};
}

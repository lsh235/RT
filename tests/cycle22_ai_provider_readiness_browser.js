async page => {
let statusCallIndex = 0;
const statusModes = ['ready','copilot-ready','sign-in','sdk-missing','unavailable'];
const consoleErrors = [];
const aiCalls = [];
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname === '/favicon.ico') return route.fulfill({status:204,body:''});
  if (!url.pathname.startsWith('/api/')) return route.continue();
  if (url.pathname.startsWith('/api/ai/')) aiCalls.push(url.pathname);
  if (url.pathname === '/api/ai/status') {
    const item = (id, name, mode) => {
      if (mode === 'ready') return {id,available:true,auth_state:'ready',models:['synthetic-model'],default_model:'synthetic-model',fixture_mode:mode};
      if (mode === 'sign-in') return {id,available:false,auth_state:'sign_in_required',error_code:'sign_in_required',models:[],fixture_mode:mode};
      if (mode === 'sdk-missing') return {id,available:false,auth_state:'sdk_missing',error_code:'sdk_missing',models:[],fixture_mode:mode};
      return {id,available:false,auth_state:'unavailable',error_code:'unavailable',models:[],fixture_mode:mode};
    };
    const mode = statusModes[Math.min(statusCallIndex++,statusModes.length-1)];
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({providers:[
      item('codex','Codex',mode === 'copilot-ready' ? 'unavailable' : mode),
      item('copilot','GitHub Copilot',mode === 'copilot-ready' ? 'ready' : (mode.startsWith('copilot-') ? mode.slice(8) : 'unavailable'))
    ]})});
  }
  if (url.pathname === '/api/health') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({version:'0.17.3'})});
  if (url.pathname === '/api/codebase-status') return route.fulfill({status:200,contentType:'application/json',body:'{}'});
  if (url.pathname === '/api/concepts/list') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({concepts:[]})});
  if (url.pathname === '/api/concepts/runs') return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({runs:[]})});
  return route.fulfill({status:200,contentType:'application/json',body:'{}'});
});
page.on('console', message => { if (message.type()==='error') consoleErrors.push(message.text()); });
await page.reload();
const require=(condition,message)=>{if(!condition)throw new Error(message);};
const waitReady=()=>page.waitForFunction(()=>!document.querySelector('#ai-provider-status').textContent.includes('확인 중'));
await waitReady();
const ready=await page.evaluate(()=>({status:document.querySelector('#ai-provider-status').textContent,
 hint:document.querySelector('#ai-setup-hint').textContent,live:document.querySelector('#ai-provider-status').getAttribute('aria-live'),
 sendDisabled:document.querySelector('#ai-send').disabled,version:document.querySelector('#server-version').textContent}));
require(ready.status==='SDK·로그인 상태 확인됨'&&!/요청 가능|응답 성공|성공 보장|항상 사용할 수/.test(ready.status),`ready provider status implies request/inference success: ${JSON.stringify(ready)}`);
require(/SDK와 로그인 상태만 확인/.test(ready.hint)&&/접근 권한/.test(ready.hint)&&/사용 한도/.test(ready.hint)&&/요청 결과에서만/.test(ready.hint),`request-specific access/usage/response boundary is unclear: ${ready.hint}`);
require(/이 앱의 별도 세션/.test(ready.hint)&&/기존 Codex·Copilot 대화를 불러오지 않습니다/.test(ready.hint),`app-scoped session caveat missing: ${ready.hint}`);
require(ready.live==='polite'&&ready.version==='v0.17.3',`status accessibility or displayed version mismatch: ${JSON.stringify(ready)}`);

await page.evaluate(()=>{state.connected=true;renderAiProviderStatus();});
require(!(await page.locator('#ai-send').isDisabled()),'send-button connected/available gating changed');
await page.locator('#ai-provider').selectOption('copilot');
await page.locator('#ai-refresh-status').click();
await page.waitForFunction(()=>document.querySelector('#ai-provider-status').textContent==='SDK·로그인 상태 확인됨');
const copilotReady=await page.evaluate(()=>({status:document.querySelector('#ai-provider-status').textContent,hint:document.querySelector('#ai-setup-hint').textContent,sendDisabled:document.querySelector('#ai-send').disabled,selected:document.querySelector('#ai-provider').value,providers:state.aiProviders}));
require(copilotReady.status==='SDK·로그인 상태 확인됨'&&copilotReady.hint.includes('GitHub Copilot')&&!copilotReady.sendDisabled,`Copilot ready state inaccurate or send gating changed; calls=${JSON.stringify(aiCalls)}: ${JSON.stringify(copilotReady)}`);

const checkState=async(mode,providerId,expectedStatus,expectedHint)=>{
  if (providerId) await page.locator('#ai-provider').selectOption(providerId);
  await page.locator('#ai-refresh-status').click();
  try { await page.waitForFunction((expected)=>document.querySelector('#ai-provider-status').textContent.includes(expected),expectedStatus,{timeout:5000}); }
  catch { throw new Error(`provider status wait failed; selected=${await page.locator('#ai-provider').inputValue()} providers=${JSON.stringify(await page.evaluate(()=>state.aiProviders))} calls=${JSON.stringify(aiCalls)} index=${statusCallIndex}`); }
  const state=await page.evaluate(()=>({status:document.querySelector('#ai-provider-status').textContent,hint:document.querySelector('#ai-setup-hint').textContent,sendDisabled:document.querySelector('#ai-send').disabled}));
  require(state.status.includes(expectedStatus)&&state.hint.includes(expectedHint)&&state.sendDisabled,`provider unavailable state or send gating mismatch for ${mode}: ${JSON.stringify(state)}`);
  return state;
};
const signedOut=await checkState('sign-in','codex','로그인이 필요합니다','이 서버에서 선택한 구독으로 로그인');
const missingSdk=await checkState('sdk-missing','codex','SDK 설치가 필요합니다','선택 기능을 설치');
const unavailable=await checkState('unavailable','codex','현재 사용할 수 없습니다','직접 검색과 평가');
require(aiCalls.length>=4&&aiCalls.every(path=>path==='/api/ai/status'),`provider status check made an inference/session request: ${JSON.stringify(aiCalls)}`);
await page.setViewportSize({width:390,height:844});
const mobile=await page.evaluate(()=>({width:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));
require(mobile.documentWidth<=mobile.width&&mobile.bodyWidth<=mobile.width,`390px horizontal overflow: ${JSON.stringify(mobile)}`);
require(consoleErrors.length===0,`application console errors after mocked reload: ${JSON.stringify(consoleErrors)}`);
console.log(JSON.stringify({ready,copilotReady,signedOut,missingSdk,unavailable,aiCalls,mobile,consoleErrors}));
}

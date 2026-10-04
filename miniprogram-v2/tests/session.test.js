const { test } = require('node:test');
const assert = require('node:assert/strict');
const { storage } = require('./helpers');
const { createSession } = require('../services/session');
const { createContextStore } = require('../stores/context');
const { createApi } = require('../services/api');
function setup() {
  const wx = storage(); const context = createContextStore();
  const session = createSession(wx, context);
  session.set({ token: 't1', user: { id: '9007199254740993' } });
  return { wx, context, session };
}
test('account switch clears old scoped state, preserves opaque string ids', () => {
  const {wx,session} = setup();
  session.write('8','children',[{id:'9'}]);
  session.set({token:'t2',user:{id:'2'}});
  assert.equal(session.read('8','children'), undefined);
  assert.equal(wx.getStorageInfoSync().keys.some(k=>k.startsWith('v2:9007199254740993:')), false);
  assert.equal(session.user().id,'2');
});
test('pending invitation survives first login and clears on logout', () => {
  const wx=storage(); const s=createSession(wx,createContextStore());
  s.pending('secret'); s.set({token:'t',user:{id:'1'}});
  assert.equal(s.pending(),'secret');
  s.logout(); assert.equal(s.pending(), undefined);
});
test('scoped idempotency key persists across restarts and changes only for different payload', () => {
  const {wx,session}=setup();
  const a=session.mutationKey('8','create',{name:'A'});
  const b=createSession(wx,createContextStore());
  assert.equal(b.mutationKey('8','create',{name:'A'}),a);
  assert.notEqual(b.mutationKey('8','create',{name:'B'}),a);
});
test('network errors retain session and cache; 403 retains credentials', async () => {
  const {wx,session,context}=setup(); session.write('8','children',[]);
  wx.request=o=>o.fail({});
  const api=createApi(wx,session,context);
  await assert.rejects(api.request('/me'), e=>e.code==='NETWORK');
  assert.equal(session.token(),'t1'); assert.deepEqual(session.read('8','children'),[]);
  wx.request=o=>o.success({statusCode:403,data:{error:{code:'FORBIDDEN',message:'No',request_id:'r'}}});
  await assert.rejects(api.request('/me'),e=>e.code==='FORBIDDEN' && e.requestId==='r');
  assert.equal(session.token(),'t1');
});
test('current 401 clears identity/cache and sends login once', async () => {
  const {wx,session,context}=setup(); let redirects=0;
  wx.reLaunch=()=>redirects++;
  wx.request=o=>o.success({statusCode:401,data:{error:{code:'UNAUTHORIZED',message:'Expired'}}});
  await assert.rejects(createApi(wx,session,context).request('/me'));
  assert.equal(session.token(),undefined); assert.equal(redirects,1);
});
test('expired invitation login preserves only its pending token for preview after login', async () => {
  const {wx,session,context}=setup(); session.pending('invite'); session.write('8','children',[]);
  wx.reLaunch=()=>{};
  wx.request=o=>o.success({statusCode:401,data:{error:{code:'UNAUTHORIZED'}}});
  await assert.rejects(createApi(wx,session,context).request('/invitations/preview',{method:'POST',data:{token:'invite'}}));
  assert.equal(session.token(),undefined); assert.equal(session.pending(),'invite');
  session.set({token:'new',user:{id:'9007199254740993'}});
  assert.equal(session.pending(),'invite'); assert.equal(session.read('8','children'),undefined);
});
test('late 401 from previous account cannot log out new account', async () => {
  const {wx,session,context}=setup(); let request;
  wx.request=o=>request=o;
  const promise=createApi(wx,session,context).request('/me');
  session.set({token:'t2',user:{id:'2'}});
  request.success({statusCode:401,data:{error:{code:'UNAUTHORIZED'}}});
  await assert.rejects(promise,e=>e.code==='STALE');
  assert.equal(session.token(),'t2');
});
test('late family response is discarded, invitation 410 leaves family intact', async () => {
  const {wx,session,context}=setup(); let request;
  context.select({familyId:'8'});
  wx.request=o=>request=o;
  const api=createApi(wx,session,context); const p=api.request('/families/8/children');
  context.select({familyId:'9'}); request.success({statusCode:200,data:[]});
  await assert.rejects(p,e=>e.code==='STALE');
  wx.request=o=>o.success({statusCode:410,data:{error:{code:'INVITATION_EXPIRED',message:'Expired'}}});
  await assert.rejects(api.request('/invitations/preview',{method:'POST',data:{token:'x'}}));
  assert.equal(context.capture().current.familyId,'9'); assert.equal(session.token(),'t1');
});
test('successful request preserves plain arrays and sends persistent mutation header', async () => {
  const {wx,session,context}=setup(); let sent;
  wx.request=o=>{sent=o; o.success({statusCode:201,data:[{id:'9007199254740999'}]});};
  const result=await createApi(wx,session,context).request('/families',{method:'POST',data:{name:'A'},idempotencyKey:'key'});
  assert.equal(sent.url,'http://127.0.0.1:8001/v2/families');
  assert.equal(sent.header['Idempotency-Key'],'key');
  assert.equal(result[0].id,'9007199254740999');
});

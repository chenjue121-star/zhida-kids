const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {storage}=require('./helpers');
const {createSession}=require('../services/session');
const {createContextStore}=require('../stores/context');
function setup(handler){
 const platform=storage(),context=createContextStore(),session=createSession(platform,context),calls=[];
 session.set({token:'t',user:{id:'u'}});session.capability('f','editor');context.select({familyId:'f',childId:'a'});
 const api={request:async(url,options={})=>{calls.push({url,options});return handler?handler(url,options):{status:'completed',plan:{id:'p',version:1}};}};
 const file=path.resolve(__dirname,'../services/outfits.js');assert.ok(fs.existsSync(file),'Phase C outfit service exists');
 const service=require(file).createOutfits(api,session,context);
 return {platform,context,session,calls,service};
}
const body=()=>({child_id:'a',target_date:'2026-10-03',draft_id:'d',action_id:'action-a',scene:'daily',preference_mode:'family',main_items:[{garment_id:'g',expected_version:1}],backup:{mode:'none',items:[]},input_version:'v'});
const lost=()=>Object.assign(new Error('lost'),{code:'NETWORK'});
test('C service sends the unified paths and editing scope without changing opaque IDs',async()=>{
 const h=setup();await h.service.context('f',{child_id:'9007199254740993',date_mode:'tomorrow'});
 assert.match(h.calls[0].url,/\/families\/f\/outfits\/context\?child_id=9007199254740993&date_mode=tomorrow$/);assert.equal(h.calls[0].options.editScope,undefined);
 for(const method of ['recommend','candidates','backup','review','sharing']){await h.service[method]('f',body());assert.equal(h.calls.at(-1).options.editScope,true);assert.equal(h.calls.at(-1).options.method,'POST');assert.ok(h.calls.at(-1).url.endsWith('/'+method));}
});
test('save freezes original payload across lost response and another same-day draft',async()=>{
 const h=setup((url,options)=>{if(options.method==='POST')throw lost();return {status:'unknown'};});
 const payload=body();await assert.rejects(h.service.save('f',payload),e=>e.code==='RESULT_UNKNOWN');
 const pending=h.service.pending('f',payload.target_date);payload.main_items[0].garment_id='changed';
 assert.equal(pending.payload.main_items[0].garment_id,'g');assert.ok(pending.operation_id);
 await assert.rejects(h.service.save('f',{...body(),draft_id:'different',main_items:[]}),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);assert.ok(h.calls.at(-1).url.endsWith('/operations/'+pending.operation_id));
});
test('pending save survives restart and queries only its original operation',async()=>{
 const h=setup(()=>{throw lost();});await assert.rejects(h.service.save('f',body()));
 const original=h.service.pending('f','2026-10-03').operation_id;
 const freshSession=createSession(h.platform,h.context);freshSession.capability('f','editor');const calls=[];
 const fresh=require('../services/outfits').createOutfits({request:async(url,options)=>{calls.push({url,options});return {status:'unknown'};}},freshSession,h.context);
 await assert.rejects(fresh.save('f',body()),e=>e.code==='RESULT_UNKNOWN');assert.equal(calls.length,1);assert.equal(calls[0].options.method,'GET');assert.ok(calls[0].url.endsWith('/'+original));
});
test('NOT_FOUND and failed queries retain unknown receipt and never send a new save',async()=>{
 let lookup=false;const h=setup((url,options)=>{if(options.method==='POST')throw lost();throw Object.assign(new Error('not yet found'),{code:lookup?'NETWORK':'NOT_FOUND',status:lookup?undefined:404});});
 await assert.rejects(h.service.save('f',body()));const original=h.service.pending('f','2026-10-03').operation_id;
 await assert.rejects(h.service.queryOperation('f','2026-10-03'),e=>e.code==='RESULT_UNKNOWN');lookup=true;
 await assert.rejects(h.service.queryOperation('f','2026-10-03'),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(h.service.pending('f','2026-10-03').operation_id,original);assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);
});
test('viewer may query original success at new access epoch without current garment revalidation',async()=>{
 let result={status:'unknown'};const h=setup((url,options)=>{if(options.method==='POST')throw lost();return result;});
 await assert.rejects(h.service.save('f',body()));h.session.capability('f','viewer');
 result={status:'completed',operation_id:h.service.pending('f','2026-10-03').operation_id,plan:{id:'p',version:1,main_items:[{garment_id:'g',state:'ready'}]}};
 const receipt=await h.service.queryOperation('f','2026-10-03');assert.equal(receipt.plan.id,'p');assert.equal(h.service.pending('f','2026-10-03'),null);
 assert.equal(h.calls.at(-1).options.editScope,undefined);assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);
 assert.deepEqual(await h.service.queryOperation('f','2026-10-03'),receipt);
});
test('resolve sends frozen original payload and NOT_EXECUTED unlocks recheck with a new identity',async()=>{
 const h=setup((url,options)=>{if(url.endsWith('/resolve'))return {status:'completed',error:{code:'NOT_EXECUTED'}};if(options.method==='POST')throw lost();return {status:'unknown'};});
 await assert.rejects(h.service.save('f',body()));const original=h.service.pending('f','2026-10-03');
 const result=await h.service.resolveOperation('f','2026-10-03');assert.equal(result.error.code,'NOT_EXECUTED');assert.deepEqual(h.calls.at(-1).options.data,original.payload);assert.equal(h.service.pending('f','2026-10-03'),null);
 await assert.rejects(h.service.save('f',{...body(),action_id:'new-action',input_version:'rechecked'}));assert.notEqual(h.service.pending('f','2026-10-03').operation_id,original.operation_id);
});
test('separate target dates keep independent pending saves',async()=>{
 const h=setup(()=>{throw lost();});await assert.rejects(h.service.save('f',body()));await assert.rejects(h.service.save('f',{...body(),target_date:'2026-10-04'}));
 assert.equal(h.calls.length,2);assert.notEqual(h.service.pending('f','2026-10-03').operation_id,h.service.pending('f','2026-10-04').operation_id);
});
test('viewer cannot request suggestions or resolve pending mutation',async()=>{
 const h=setup();h.session.capability('f','viewer');for(const method of ['recommend','candidates','backup','review','sharing','save'])await assert.rejects(h.service[method]('f',body()),e=>e.code==='EDIT_ACCESS_REVOKED');
 await assert.rejects(h.service.resolveOperation('f','2026-10-03'),e=>e.code==='EDIT_ACCESS_REVOKED');assert.equal(h.calls.length,0);
});
test('late successful save after account switch never writes into the new account partition',async()=>{
 let release;const h=setup(()=>new Promise(r=>release=r));const save=h.service.save('f',body());h.session.set({token:'new',user:{id:'other'}});h.session.capability('f','editor');release({status:'completed',plan:{id:'old-private'}});
 await assert.rejects(save,e=>['RESULT_UNKNOWN','STALE'].includes(e.code));assert.equal(h.service.pending('f','2026-10-03'),null);assert.equal(h.session.read('f','outfit-result:2026-10-03'),undefined);
});
test('permission epoch rejects late query even though transport returned success',async()=>{
 let release;const h=setup((url,options)=>options.method==='POST'?Promise.reject(lost()):new Promise(r=>release=r));await assert.rejects(h.service.save('f',body()));
 const query=h.service.queryOperation('f','2026-10-03');h.session.capability('f','viewer');release({status:'completed',plan:{id:'p'}});
 await assert.rejects(query,e=>e.code==='STALE');assert.ok(h.service.pending('f','2026-10-03'));
});
test('navigation switch rejects late recommendation without changing family storage',async()=>{
 let release;const h=setup(()=>new Promise(r=>release=r));const request=h.service.recommend('f',body());h.context.select({familyId:'other',childId:'b'});release({items:[{id:'private'}]});await assert.rejects(request,e=>e.code==='STALE');
});
test('service transports contract fields only and repeat completed save does not add a second plan',async()=>{
 const h=setup();const payload={...body(),revision:9,dirty:true,source_origin:{private:'draft'},main_items:[{id:'g',version:1,name:'display',image:'/temp/private'}]};
 await h.service.save('f',payload);const wire=h.calls[0].options.data;
 assert.equal(wire.action_id,undefined);assert.equal(wire.revision,undefined);assert.equal(wire.source_origin,undefined);assert.deepEqual(wire.main_items,[{garment_id:'g',expected_version:1}]);
 await h.service.save('f',payload);assert.equal(h.calls.length,1);
});
test('late context cannot be accepted after family membership was revoked',async()=>{
 let release;const h=setup(()=>new Promise(r=>release=r));const call=h.service.context('f',{child_id:'a'});h.session.clearFamily('f');release({role:'editor',plans:[{id:'private'}]});await assert.rejects(call,e=>e.code==='STALE');
});
test('completed action replay remains deduplicated after another same-day action succeeds',async()=>{
 let sequence=0;const h=setup((url,options)=>({status:'completed',operation_id:options.data.operation_id,plan:{id:'p'+(++sequence)}}));
 const first=await h.service.save('f',body());await h.service.save('f',{...body(),draft_id:'d2',action_id:'a2'});const replay=await h.service.save('f',body());
 assert.equal(replay.plan.id,first.plan.id);assert.equal(h.calls.filter(c=>c.options.method==='POST').length,2);
});
test('late old query cannot clear a newer pending save or pair its payload with old success',async()=>{
 const replies=[];const h=setup((url,options)=>{if(options.method==='POST')throw lost();return new Promise(r=>replies.push(r));});
 await assert.rejects(h.service.save('f',body()));const a=h.service.pending('f','2026-10-03');
 const first=h.service.queryOperation('f','2026-10-03'),second=h.service.queryOperation('f','2026-10-03');
 replies[0]({status:'completed',operation_id:a.operation_id,plan:{id:'old-a'}});await first;
 await assert.rejects(h.service.save('f',{...body(),draft_id:'b',action_id:'b'}));const b=h.service.pending('f','2026-10-03');
 replies[1]({status:'completed',operation_id:a.operation_id,plan:{id:'old-a'}});await second;
 assert.equal(h.service.pending('f','2026-10-03').operation_id,b.operation_id);assert.equal(h.service.pending('f','2026-10-03').payload.draft_id,'b');
});
test('input version is sent only to save while server review receives backup recheck flag',async()=>{
 const h=setup();const payload={...body(),backup_needs_review:true};
 for(const method of ['recommend','candidates','backup','review','sharing']){await h.service[method]('f',payload);assert.equal(h.calls.at(-1).options.data.input_version,undefined);assert.equal(h.calls.at(-1).options.data.backup_needs_review,true);}
 await h.service.save('f',payload);assert.equal(h.calls.at(-1).options.data.input_version,'v');
});
test('backup candidate usage is retained without transmitting unrelated draft metadata',async()=>{const h=setup();await h.service.candidates('f',{...body(),usage:'backup',replace_id:'g',dirty:true});assert.equal(h.calls[0].options.data.usage,'backup');assert.equal(h.calls[0].options.data.dirty,undefined);});
test('another child same-day save remains independent of the original unknown operation',async()=>{
 const h=setup((url,options)=>{if(options.method==='POST')throw lost();return {status:'completed',plan:{id:'plan-a',child_id:'a'}};});
 await assert.rejects(h.service.save('f',body()));h.context.select({familyId:'f',childId:'b'});
 await assert.rejects(h.service.save('f',{...body(),child_id:'b',draft_id:'b',action_id:'b'}),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(h.calls.length,2);const pendingB=h.service.pending('f','2026-10-03','b');assert.equal(pendingB.payload.child_id,'b');
 const result=await h.service.queryOperation('f','2026-10-03','a');assert.equal(result.plan.child_id,'a');assert.deepEqual(h.service.pending('f','2026-10-03','b'),pendingB);
});

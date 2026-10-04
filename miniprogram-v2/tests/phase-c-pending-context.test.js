const {test}=require('node:test');
const assert=require('node:assert/strict');
const {storage}=require('./helpers');
const {createSession}=require('../services/session');
const {createContextStore}=require('../stores/context');
const {createOutfits}=require('../services/outfits');
const {createOutfitStore}=require('../stores/outfit-context');
const date='2026-10-03';
const lost=()=>Object.assign(new Error('lost'),{code:'NETWORK'});
const payload=(child='a',action=child)=>({child_id:child,target_date:date,draft_id:'draft-'+action,action_id:'action-'+action,scene:'daily',preference_mode:'family',main_items:[{garment_id:'garment-'+child,expected_version:1}],backup:{mode:'none',items:[]},input_version:'reviewed'});
function setup(handler){const platform=storage(),context=createContextStore(),session=createSession(platform,context),calls=[];session.set({token:'fixture',user:{id:'fixture-u'}});session.capability('f','editor');context.select({familyId:'f',childId:'a'});const api={request:async(url,options={})=>{calls.push({url,options});return handler(url,options);}};return {platform,context,session,calls,service:createOutfits(api,session,context),store:createOutfitStore(session,context)};}
function legacy(child='a'){const original=payload(child);return {operation_id:'legacy-'+child,mutation_slot:'legacy-action-'+child,payload:{...original,operation_id:'legacy-'+child}};}
test('A pending stays immutable while B same-day save succeeds under its own identity',async()=>{
 const h=setup((url,o)=>o.method==='POST'?(o.data.child_id==='a'?Promise.reject(lost()):{status:'completed',operation_id:o.data.operation_id,plan:{id:'plan-b',child_id:'b'}}):{status:'unknown'});
 h.store.open('f','a',date);h.store.patch({main_items:[{id:'ga',version:1}]});const a=h.store.get(),frozen={...h.store.payload(),input_version:'reviewed'};
 await assert.rejects(h.service.save('f',frozen),e=>e.code==='RESULT_UNKNOWN');const original=h.service.pending('f',date,'a');assert.throws(()=>h.store.patch({scene:'outdoor'}),e=>e.code==='RESULT_UNKNOWN');
 h.context.select({familyId:'f',childId:'b'});h.store.open('f','b',date);h.store.patch({main_items:[{id:'gb',version:1}]});const selected=await h.service.save('f',{...h.store.payload(),input_version:'reviewed'});
 assert.equal(selected.plan.child_id,'b');assert.deepEqual(h.service.pending('f',date,'a'),original);assert.equal(h.service.pending('f',date,'b'),null);
 h.context.select({familyId:'f',childId:'a'});h.store.open('f','a',date);assert.equal(h.store.get().draft_id,a.draft_id);assert.throws(()=>h.store.fixed('ga',true),e=>e.code==='RESULT_UNKNOWN');
 assert.equal(h.calls.filter(c=>c.options.method==='POST').length,2);
});
test('same child and date blocks an independent action regardless of preference basis',async()=>{
 const h=setup((url,o)=>o.method==='POST'?Promise.reject(lost()):{status:'unknown'});await assert.rejects(h.service.save('f',payload()));const original=h.service.pending('f',date,'a');
 await assert.rejects(h.service.save('f',{...payload('a','different'),preference_mode:'current_member'}),e=>e.code==='RESULT_UNKNOWN');assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);assert.deepEqual(h.service.pending('f',date,'a'),original);
});
test('both child pending records survive and resolving A only fences A frozen payload',async()=>{
 const h=setup((url,o)=>url.endsWith('/resolve')?{status:'completed',operation_id:o.data.operation_id,plan:null,error:{code:'NOT_EXECUTED'}}:o.method==='POST'?Promise.reject(lost()):{status:'unknown'});
 await assert.rejects(h.service.save('f',payload('a')));h.context.select({familyId:'f',childId:'b'});await assert.rejects(h.service.save('f',payload('b')));const a=h.service.pending('f',date,'a'),b=h.service.pending('f',date,'b');
 assert.notEqual(a.operation_id,b.operation_id);await assert.rejects(h.service.queryOperation('f',date,'a'),e=>e.code==='RESULT_UNKNOWN');assert.ok(h.calls.at(-1).url.endsWith('/'+a.operation_id));
 const result=await h.service.resolveOperation('f',date,'a');assert.equal(result.error.code,'NOT_EXECUTED');assert.deepEqual(h.calls.at(-1).options.data,a.payload);assert.equal(h.service.pending('f',date,'a'),null);assert.deepEqual(h.service.pending('f',date,'b'),b);
});
test('legacy date-only A pending remains recoverable beside new child B pending',async()=>{
 const h=setup((url,o)=>url.endsWith('/resolve')?{status:'completed',operation_id:o.data.operation_id,plan:null,error:{code:'NOT_EXECUTED'}}:o.method==='POST'?Promise.reject(lost()):{status:'unknown'}),a=legacy();h.session.write('f','outfit-pending:'+date,a);h.context.select({familyId:'f',childId:'b'});
 await assert.rejects(h.service.save('f',payload('b')));const b=h.service.pending('f',date,'b');assert.equal(b.payload.child_id,'b');assert.deepEqual(h.session.read('f','outfit-pending:'+date),a);
 await assert.rejects(h.service.queryOperation('f',date,'a'),e=>e.code==='RESULT_UNKNOWN');assert.ok(h.calls.at(-1).url.endsWith('/legacy-a'));await h.service.resolveOperation('f',date,'a');assert.equal(h.session.read('f','outfit-pending:'+date),undefined);assert.deepEqual(h.service.pending('f',date,'b'),b);
});
test('legacy history is selected by original child and never overwritten by B result',async()=>{
 const h=setup((url,o)=>({status:'completed',operation_id:o.data.operation_id,plan:{id:'plan-b',child_id:'b'}})),a=legacy();const history={receipt:{status:'completed',operation_id:a.operation_id,plan:{id:'historic-a',child_id:'a',version:1}},payload:a.payload};h.session.write('f','outfit-result:'+date,history);h.context.select({familyId:'f',childId:'b'});
 assert.deepEqual(await h.service.queryOperation('f',date,'b'),{status:'not_pending'});const result=await h.service.save('f',payload('b'));assert.equal(result.plan.id,'plan-b');assert.deepEqual(h.session.read('f','outfit-result:'+date),history);
 assert.equal((await h.service.queryOperation('f',date,'a')).plan.id,'historic-a');assert.equal((await h.service.queryOperation('f',date,'b')).plan.id,'plan-b');assert.equal(h.calls.length,1);
});
test('late A query can complete A only while B remains pending in the same active context',async()=>{
 let release;const h=setup((url,o)=>o.method==='POST'?Promise.reject(lost()):new Promise(r=>release=r));await assert.rejects(h.service.save('f',payload('a')));h.context.select({familyId:'f',childId:'b'});await assert.rejects(h.service.save('f',payload('b')));const a=h.service.pending('f',date,'a'),b=h.service.pending('f',date,'b');
 const query=h.service.queryOperation('f',date,'a');release({status:'completed',operation_id:a.operation_id,plan:{id:'plan-a',child_id:'a'}});assert.equal((await query).plan.child_id,'a');assert.equal(h.service.pending('f',date,'a'),null);assert.deepEqual(h.service.pending('f',date,'b'),b);
});
for(const status of [422,409])test('old definitive POST '+status+' cannot remove a newer same-child operation after resolve',async()=>{
 let rejectOld;const h=setup((url,o)=>url.endsWith('/resolve')?{status:'completed',operation_id:o.data.operation_id,plan:null,error:{code:'NOT_EXECUTED'}}:o.data.draft_id==='draft-a'?new Promise((resolve,reject)=>rejectOld=reject):Promise.reject(lost()));
 const old=h.service.save('f',payload('a')),oldRejected=assert.rejects(old,e=>e.status===status);await h.service.resolveOperation('f',date,'a');await assert.rejects(h.service.save('f',payload('a','new')));const current=h.service.pending('f',date,'a'),mutation=h.session.read('f','mutation:'+current.mutation_slot);
 rejectOld(Object.assign(new Error('late validation failure'),{status,code:'GARMENT_UNAVAILABLE'}));await oldRejected;assert.deepEqual(h.service.pending('f',date,'a'),current);assert.deepEqual(h.session.read('f','mutation:'+current.mutation_slot),mutation);
});
test('navigation and new identity reject late A receipt without touching B partition',async()=>{
 let release;const h=setup((url,o)=>o.method==='POST'?Promise.reject(lost()):new Promise(r=>release=r));await assert.rejects(h.service.save('f',payload()));const query=h.service.queryOperation('f',date,'a'),rejected=assert.rejects(query,e=>e.code==='STALE');
 h.session.set({token:'new-fixture',user:{id:'new-fixture-user'}});h.session.capability('f','editor');h.context.select({familyId:'f',childId:'b'});release({status:'completed',plan:{id:'private-a',child_id:'a'}});await rejected;assert.equal(h.service.pending('f',date,'a'),null);assert.deepEqual(await h.service.queryOperation('f',date,'b'),{status:'not_pending'});
});
test('legacy result containing only response.plan restores its original child and date',async()=>{
 const h=setup(()=>{throw new Error('cached history must not send a request');});
 const response={status:'completed',operation_id:'old-history',plan:{id:'old-plan-a',child_id:'a',target_date:date,version:1}};
 h.session.write('f','outfit-result:'+date,{response});h.context.select({familyId:'f',childId:'b'});
 assert.deepEqual(await h.service.queryOperation('f',date,'b'),{status:'not_pending'});
 assert.deepEqual(await h.service.queryOperation('f',date,'a'),response);
 assert.deepEqual(await h.service.queryOperation('f','2026-10-04','a'),{status:'not_pending'});
 assert.deepEqual(h.session.read('f','outfit-result:'+date),{response});
});
test('shared draft presentation passes the draft child explicitly to pending lookup',()=>{
 const path=require('node:path'),root=path.resolve(__dirname,'..');for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/')||key.startsWith(root+'/stores/'))delete require.cache[key];
 global.wx=storage();const rt=require('../services/runtime').getRuntime();rt.session.set({token:'fixture',user:{id:'fixture'}});require('../services/page').selectFamily('f');require('../services/page').selectChild('b');rt.session.capability('f','editor');
 rt.outfitStore.open('f','a',date);const draft=rt.outfitStore.get();rt.outfits.pending=(f,d,child)=>{assert.equal(f,'f');assert.equal(d,date);assert.equal(child,'a');return {payload:{draft_id:draft.draft_id,child_id:'a',target_date:date}};};
 const page={familyId:'f',data:{},setData(value){Object.assign(this.data,value);}};require('../services/outfit-view').sync(page);assert.equal(page.data.unknownResult,true);assert.equal(page.data.draftFrozen,true);
});
function pageHarness(name){
 const path=require('node:path'),root=path.resolve(__dirname,'..');for(const key of Object.keys(require.cache))if(['/services/','/stores/','/pages/'].some(part=>key.startsWith(root+part)))delete require.cache[key];
 const platform=storage();Object.assign(platform,{request(){},showModal:o=>o.success({confirm:true}),navigateTo(){},reLaunch(){},getLocation:o=>o.fail({})});global.wx=platform;
 let def;global.Page=d=>def=d;require('../pages/'+name+'/'+name);delete global.Page;const p={...def,data:structuredClone(def.data),setData(value){Object.assign(this.data,value);}};
 const rt=require('../services/runtime').getRuntime(),page=require('../services/page');rt.session.set({token:'fixture',user:{id:'fixture-u'}});page.selectFamily('f');page.selectChild('a');rt.session.capability('f','editor');rt.outfitStore.open('f','a',date);rt.outfitStore.patch({main_items:[{id:'ga',version:1,name:'A的主件'}]});
 p.familyId='f';p._visible=true;Object.assign(p.data,{ready:true,writable:true,targetDate:date,draft:rt.outfitStore.get(),review:{valid:true,input_version:'reviewed'}});return {p,rt,page};
}
test('home pending status explicitly belongs to the displayed child',async()=>{
 const {p,rt}=pageHarness('home');p.data.child={id:'a'};rt.outfits.context=async()=>({child:{id:'a'},target_date:date,today:date,role:'editor',weather:{status:'unknown'},plans:[],garments:[]});let checked=0;
 rt.outfits.pending=(f,d,child)=>{checked++;assert.equal(f,'f');assert.equal(d,date);assert.equal(child,'a');return null;};
 await p.loadWeather();assert.equal(p.data.error,'');assert.ok(checked>=2);assert.equal(p.data.unknownResult,false);
});
test('review query and resolve explicitly use the original displayed child',async()=>{
 const {p,rt}=pageHarness('outfit-review'),original={operation_id:'a-op',payload:rt.outfitStore.payload()};p._pendingSnapshot=structuredClone(original.payload);p.data.unknownResult=true;let queries=0,resolves=0;
 rt.outfits.pending=(f,d,child)=>{assert.equal(child,'a');return original;};
 rt.outfits.queryOperation=async(f,d,child)=>{queries++;assert.equal(child,'a');return {status:'completed',error:{code:'NOT_EXECUTED'}};};
 rt.outfits.resolveOperation=async(f,d,child)=>{resolves++;assert.equal(child,'a');return {status:'completed',error:{code:'NOT_EXECUTED'}};};
 await p.query();p.data.unknownResult=true;await p.resolve();assert.equal(queries,1);assert.equal(resolves,1);assert.equal(p.data.notSaved,true);
});
test('a late save page continuation cannot inspect or change another child display',async()=>{
 const {p,rt,page}=pageHarness('outfit-review');let release,checked=0,refreshed=0;rt.outfits.save=()=>new Promise(r=>release=r);const saving=p.performSave();
 page.selectChild('b');rt.outfitStore.open('f','b',date);rt.outfitStore.patch({main_items:[{id:'gb',version:1,name:'B的主件'}]});p.data.draft=rt.outfitStore.get();p.data.unknownResult=false;
 rt.outfits.pending=()=>{checked++;return {payload:payload('b')};};p.refreshDisplay=()=>{refreshed++;};release({status:'completed',plan:{id:'plan-a',child_id:'a'}});await saving;
 assert.equal(checked,0);assert.equal(refreshed,0);assert.equal(p.data.unknownResult,false);assert.equal(p.data.completedPlan,null);assert.equal(rt.outfitStore.get().child_id,'b');
});
for(const kind of ['pending','result'])test('revoked family access refuses '+kind+' operation reads without sending a request',async()=>{
 const h=setup(()=>({status:'completed',plan:{id:'private',child_id:'a'}})),original=legacy();
 const record=kind==='pending'?original:{payload:original.payload,receipt:{status:'completed',plan:{id:'private',child_id:'a',target_date:date}}};h.session.write('f','outfit-'+kind+':'+date,record);h.session.capability('f',null);
 await assert.rejects(h.service.queryOperation('f',date,'a'),e=>e.code==='FAMILY_ACCESS_REVOKED');assert.equal(h.calls.length,0);assert.equal(h.service.pending('f',date,'a'),null);assert.deepEqual(h.session.read('f','outfit-'+kind+':'+date),record);
});
function cachedPage(){
 const h=pageHarness('outfit-review'),original=h.rt.outfitStore.payload(),plan={id:'private-history',version:1,child_id:'a',target_date:date,main_items:[{id:'ga',version:1,name:'原成功主件'}],backup:{mode:'none',items:[]}},receipt={status:'completed',plan};
 h.rt.session.write('f','outfit-result:'+date,{receipt,payload:original});h.p._pendingSnapshot=structuredClone(original);h.p.data.unknownResult=true;h.p.data.draftFrozen=true;h.rt.outfits.context=async()=>({plans:[],child:{id:'a'},garments:[{id:'ga',version:2,state:'washing'}]});return {...h,plan};
}
test('revocation clears unknown presentation and a cached receipt cannot revive it through page query',async()=>{
 const {p,rt}=cachedPage();rt.session.capability('f',null);p.onEditRevoked();await p.query();
 assert.equal(p.data.unknownResult,false);assert.equal(p.data.draftFrozen,false);assert.equal(p._pendingSnapshot,null);assert.equal(p.data.ready,false);assert.equal(p.data.completedPlan,null);assert.equal(p.data.completedView,null);assert.equal(p.data.reviewSnapshot,null);assert.deepEqual(p.data.packingItems,[]);
});
test('cached receipt microtask arriving after revocation cannot restore a private completed view',async()=>{
 const {p,rt}=cachedPage();const querying=p.query();rt.session.capability('f',null);p.onEditRevoked();await querying;
 assert.equal(p.data.ready,false);assert.equal(p.data.unknownResult,false);assert.equal(p.data.completedPlan,null);assert.equal(p.data.completedView,null);assert.deepEqual(p.data.packingItems,[]);
});
test('a viewer may freshly recover original historical success but cannot save or resolve',async()=>{
 const {p,rt,plan}=cachedPage();rt.session.capability('f','viewer');p.onEditRevoked();await p.query();
 assert.deepEqual(p.data.completedPlan,plan);assert.equal(p.data.completedView.main_items[0].name,'原成功主件');assert.equal(p.data.completedView.main_items[0].version,1);assert.equal(p.data.writable,false);
 let saved=0,resolved=0;rt.outfits.save=async()=>{saved++;};rt.outfits.resolveOperation=async()=>{resolved++;};p.save();await p.resolve();assert.equal(saved,0);assert.equal(resolved,0);
});
for(const method of ['performSave','resolve'])test('late '+method+' receipt after access epoch changes cannot recreate completed presentation',async()=>{
 const {p,rt,plan}=cachedPage();p.data.unknownResult=false;p.data.draftFrozen=false;let release,calls=0,notes=0;const service=method==='performSave'?'save':'resolveOperation';
 rt.outfits[service]=()=>{calls++;return new Promise(r=>release=r);};p.currentNotes=async()=>{notes++;};const operation=p[method]();await new Promise(r=>setImmediate(r));assert.equal(calls,1);
 rt.session.capability('f',null);p.onEditRevoked();release({status:'completed',plan});await operation;assert.equal(p.data.completedPlan,null);assert.equal(p.data.completedView,null);assert.equal(p.data.unknownResult,false);assert.equal(notes,0);
});

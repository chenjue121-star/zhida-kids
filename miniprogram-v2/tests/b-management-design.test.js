const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');

function harness(name){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/')||key.startsWith(root+'/pages/'))delete require.cache[key];
 const platform=storage(),nav=[],requests=[];
 Object.assign(platform,{request:o=>requests.push(o),navigateTo:o=>nav.push(o.url),navigateBack:()=>nav.push('back'),reLaunch:o=>nav.push(o.url),setNavigationBarTitle(){},showToast(){},showModal:o=>o.success({confirm:true})});
 global.wx=platform;let definition;global.Page=p=>definition=p;require('../pages/'+name+'/'+name);delete global.Page;
 const p={...definition,data:structuredClone(definition.data),setData(patch){for(const [key,value] of Object.entries(patch)){const names=key.split('.');let target=this.data;for(const part of names.slice(0,-1))target=target[part];target[names.at(-1)]=value;}}};
 const rt=require('../services/runtime').getRuntime();rt.session.set({token:'t',user:{id:'u'}});require('../services/page').selectFamily('f');rt.session.capability('f','editor');p.familyId='f';
 return {p,rt,nav,requests};
}

const garment={id:'g',version:7,name:'绿格背带裤',category:'onesie',colors:['green'],pattern:'plaid',thickness:'unknown',state:'washing',asset_id:null,owners:[{child_id:'old',nickname:'小豆子',fit:'small'}]};

test('restore shows latest removal fit as history while requiring a new current fit',()=>{
 const {p}=harness('garment-owners');p.mode='restore';
 p.initialize([{id:'old',nickname:'小豆子'}],{...garment,archived_at:'2026-10-01',last_owners:[{child_id:'old',nickname:'小豆子',fit:'small'},{child_id:'archived',nickname:'小桃',fit:'unknown',archived:true}]});
 assert.equal(p.data.garment.stateLabel,'待洗');
 assert.deepEqual(p.data.historyOwners.map(o=>[o.nickname,o.fitLabel,o.archived||false]),[['小豆子','偏小',false],['小桃','暂不清楚',true]]);
 assert.equal(p.data.choices[0].fit,'');assert.equal(p.data.canSave,false);
});

test('transfer only offers a new active user and names both sides of the change',()=>{
 const {p}=harness('garment-owners');p.mode='transfer';
 p.initialize([{id:'old',nickname:'小豆子'},{id:'new',nickname:'小花'}],garment);
 assert.deepEqual(p.data.transferChoices.map(c=>c.id),['new']);assert.equal(p.data.previousOwner.nickname,'小豆子');
 p.target({detail:{value:'0'}});
 assert.equal(p.data.targetOwner.nickname,'小花');assert.equal(p.data.canSave,false);
 p.fit({currentTarget:{dataset:{id:'new'}},detail:{value:'3'}});
 assert.equal(p.data.canSave,true);assert.equal(p.data.choices.find(c=>c.id==='new').fit,'unknown');
});

test('sharing keeps old fit and marks new selected users for explicit fit confirmation',()=>{
 const {p}=harness('garment-owners');p.mode='sharing';
 p.initialize([{id:'old',nickname:'小豆子'},{id:'new',nickname:'小花'}],garment);
 p.choose({detail:{value:['old','new']}});
 assert.equal(p.data.choices.find(c=>c.id==='old').fit,'small');assert.equal(p.data.choices.find(c=>c.id==='new').isNew,true);assert.equal(p.data.canSave,false);
});

test('detail quick status writes the displayed version and preserves each child fit',async()=>{
 const {p,rt}=harness('garment-detail');p.id='g';p.data.ready=true;p.data.writable=true;p.data.garment=garment;const writes=[];
 rt.wardrobe.update=async(f,id,body)=>{writes.push({f,id,body});return {...garment,state:body.state,version:8};};
 await p.state({detail:{value:'0'}});
 assert.deepEqual(writes,[{f:'f',id:'g',body:{state:'ready',expected_version:7}}]);assert.equal(p.data.garment.stateLabel,'可穿');assert.equal(p.data.garment.owners[0].fit,'small');
});

test('detail quick status cannot mutate archived or viewer data',async()=>{
 const {p,rt}=harness('garment-detail');p.id='g';p.data.ready=true;p.data.garment=garment;let writes=0;rt.wardrobe.update=async()=>{writes++;};
 await p.state({detail:{value:'0'}});p.data.writable=true;p.data.garment={...garment,archived_at:'2026-10-01'};await p.state({detail:{value:'0'}});assert.equal(writes,0);
});

test('detail quick status conflict exposes latest relation instead of silently retrying',async()=>{
 const {p,rt}=harness('garment-detail');p.id='g';p.data.ready=true;p.data.writable=true;p.data.garment=garment;let writes=0;
 rt.wardrobe.update=async()=>{writes++;throw Object.assign(new Error('内容已变化'),{status:409});};rt.wardrobe.get=async()=>({...garment,version:8,state:'missing'});
 await p.state({detail:{value:'0'}});
 assert.equal(writes,1);assert.equal(p.data.latest.stateLabel,'找不到');assert.equal(p.data.garment.state,'washing');assert.equal(p.data.conflict,true);
});

test('removed history filters use full family metadata beyond the loaded page',async()=>{
 const {p,rt}=harness('wardrobe-removed');const calls=[];
 rt.api.request=async url=>url.endsWith('/members')?[{user_id:'u',status:'active',role:'editor'}]:[{id:'active',nickname:'小花'}];
 rt.wardrobe.list=async(f,query)=>{calls.push(query);return {items:[],total:0,family_total:2,next_cursor:null,history_children:[{id:'remote',nickname:'小桃',archived:true}]};};
 await p.reload();assert.equal(calls.length,1);assert.ok(p.data.historyChildren.some(c=>c.id==='remote'&&c.nickname==='小桃（已归档）'));assert.ok(p.data.historyChildren.some(c=>c.id==='active'));
});

test('loading another removed page merges last users without adding lifetime-only users',async()=>{
 const {p,rt}=harness('wardrobe-removed');p.data.nextCursor='1';p.data.ready=true;
 rt.wardrobe.list=async()=>({items:[{...garment,id:'2',asset_id:null,last_owners:[{child_id:'last',nickname:'上次使用者',fit:'fit',archived:true}],history_owners:[{child_id:'earlier',nickname:'早期使用者',fit:'fit'}]}],next_cursor:null});
 await p.more();assert.ok(p.data.historyChildren.some(c=>c.id==='last'));assert.equal(p.data.historyChildren.some(c=>c.id==='earlier'),false);
});

test('history filter keeps an archived user label and chosen identity across pages',()=>{
 const {p}=harness('wardrobe-removed');p.mergeHistory({items:[],history_children:[{id:'old',nickname:'小桃',archived:true}]});p.data.filterIndex=1;
 p.mergeHistory({items:[]});assert.equal(p.data.historyChildren[p.data.filterIndex].id,'old');assert.equal(p.data.historyChildren[p.data.filterIndex].nickname,'小桃（已归档）');
});

test('rechecking a restore conflict displays already restored current fits',()=>{
 const {p}=harness('garment-owners');p.mode='restore';p.data.children=[{id:'old',nickname:'小豆子'}];p.data.latest={...garment,archived_at:null};p.data.conflict=true;p.adoptLatest();
 assert.equal(p.data.alreadyRestored,true);assert.equal(p.data.canSave,false);assert.equal(p.data.garment.owners[0].fitLabel,'偏小');
});

test('late owner-context image family revocation clears the newly shown history and photo',async()=>{
 const {p,rt}=harness('garment-owners');p.mode='restore';p.id='g';
 rt.api.request=async url=>url.endsWith('/members')?[{user_id:'u',status:'active',role:'editor'}]:[{id:'old',nickname:'小豆子'}];
 rt.wardrobe.get=async()=>({...garment,asset_id:'private',archived_at:'2026-10-01',last_owners:garment.owners});
 rt.media.image=async()=>{rt.session.clearFamily('f');throw Object.assign(new Error('家庭已不可访问'),{code:'FAMILY_ACCESS_REVOKED',familyId:'f',contextEpoch:rt.context.capture().epoch});};
 await p.reload();assert.equal(p.data.ready,false);assert.equal(p.data.garment,null);assert.deepEqual(p.data.historyOwners,[]);assert.equal(p.data.image,'');assert.equal(rt.session.token(),'t');
});

test('viewing an original image preserves an unresolved ownership conflict',async()=>{
 const {p,rt}=harness('garment-owners');p.data.garment={...garment,asset_id:'private'};p.data.conflict=true;p.data.latest=garment;rt.media.preview=async()=>{};
 await p.preview();assert.equal(p.data.conflict,true);assert.equal(p.data.latest.id,'g');
});

test('viewing an original image preserves an unresolved quick-status conflict',async()=>{
 const {p,rt}=harness('garment-detail');p.data.garment={...garment,asset_id:'private'};p.data.conflict=true;rt.media.preview=async()=>{};
 await p.preview();assert.equal(p.data.conflict,true);
});

test('a lost restore response immediately offers original-operation inspection',async()=>{
 const {p,rt}=harness('garment-owners');p.mode='restore';p.id='g';p.data.writable=true;p.initialize([{id:'old',nickname:'小豆子'}],{...garment,archived_at:'2026-10-01',last_owners:garment.owners});p.fit({currentTarget:{dataset:{id:'old'}},detail:{value:'3'}});
 rt.wardrobe.action=async()=>{rt.session.write('f','wardrobe-action:restore:g',{operation_id:'original'});throw Object.assign(new Error('结果尚待核实'),{code:'RESULT_UNKNOWN'});};
 await p.save();assert.equal(p.data.pendingRestore,true);assert.equal(p.data.choices[0].fit,'unknown');
});

test('a dropped archive response exposes its original operation immediately and query never resubmits',async()=>{
 const {p,rt,requests}=harness('garment-detail');p.id='g';p.data.ready=true;p.data.writable=true;p.data.garment=garment;
 const pending=p.archive();await new Promise(resolve=>setImmediate(resolve));
 const submit=requests.shift();assert.equal(submit.method,'POST');assert.equal(submit.data.expected_version,7);submit.fail({errMsg:'connection lost after submit'});await pending;
 assert.equal(p.data.pendingArchive,true);assert.equal(p.data.garment.archived_at,undefined);assert.equal(rt.session.read('f','wardrobe-action:archive:g').operation_id,submit.data.operation_id);
 const query=p.queryArchive(),read=requests.shift();assert.equal(read.method,'GET');assert.ok(read.url.endsWith('/wardrobe-operations/'+submit.data.operation_id));
 const archived={...garment,archived_at:'2026-10-04',version:8};read.success({statusCode:200,data:{status:'completed',results:[{status:'success',garment:archived}]}});await new Promise(resolve=>setImmediate(resolve));
 const latest=requests.shift();assert.equal(latest.method,'GET');latest.success({statusCode:200,data:archived});await query;
 assert.equal(requests.length,0);assert.equal(p.data.pendingArchive,false);assert.equal(p.data.garment.archived_at,'2026-10-04');
});

test('late archive errors cannot expose an old operation after hiding or context changes',async()=>{
 for(const transition of ['hidden','family','account']){
  const {p,rt,requests}=harness('garment-detail');p.id='g';p.data.ready=true;p.data.writable=true;p.data.garment=garment;
  const pending=p.archive();await new Promise(resolve=>setImmediate(resolve));const submit=requests.shift();
  if(transition==='hidden')p.onHide();
  if(transition==='family')require('../services/page').selectFamily('other');
  if(transition==='account')rt.session.set({token:'new',user:{id:'new'}});
  submit.fail({errMsg:'connection lost'});await pending;assert.equal(p.data.pendingArchive,false,transition);
 }
});

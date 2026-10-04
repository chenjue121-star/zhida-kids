const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');
function harness(name) {
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/') || key.startsWith(root+'/pages/'))delete require.cache[key];
 const platform=storage(); const requests=[];const nav=[];
 Object.assign(platform,{request:o=>{assert.ok(['GET','POST','PUT','DELETE','HEAD','OPTIONS','TRACE','CONNECT'].includes(o.method),'wx.request unsupported method: '+o.method);requests.push(o);},navigateTo:o=>nav.push(o.url),redirectTo:o=>nav.push(o.url),reLaunch:o=>nav.push(o.url),navigateBack:()=>nav.push('back'),showToast:()=>{},showModal:o=>o.success({confirm:true})});
 global.wx=platform;let definition;global.Page=d=>definition=d;
 require('../pages/'+name+'/'+name);delete global.Page;
 const p={...definition,data:structuredClone(definition.data),setData(patch){for(const [key,value] of Object.entries(patch)){const parts=key.split('.');let obj=this.data;for(const part of parts.slice(0,-1))obj=obj[part];obj[parts.at(-1)]=value;}}};
 const runtime=require('../services/runtime').getRuntime();runtime.session.set({token:'t',user:{id:'1'}});
 require('../services/page').selectFamily('10');
 return {p,runtime,platform,requests,nav,reply(data,statusCode=200){assert.ok(requests.length,'pending request');requests.shift().success({statusCode,data});}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('shared page defaults are retained with page-specific data',()=>{
 const {p}=harness('child-edit');assert.equal(p.data.busy,false);assert.equal(p.data.ready,false);assert.equal(p.data.error,'');
});
test('child editor starts with a compact identity and expands measurement only on demand',()=>{
 const {p}=harness('child-edit');p.childId='2';p.data.ready=true;p.data.role='editor';
 assert.equal(p.data.measurementOpen,false);
 p.toggleMeasurement();assert.equal(p.data.measurementOpen,true);
 p.toggleMeasurement();assert.equal(p.data.measurementOpen,false);
 p.data.role='viewer';p.toggleMeasurement();assert.equal(p.data.measurementOpen,false);
 p.ageYear({detail:{value:'2'}});p.ageMonth({detail:{value:'3'}});
 assert.equal(p.data.ageLabel,'2岁3个月');
});
test('family profile and member controls stay folded until selected',()=>{
 const {p}=harness('family-detail');p.data.ready=true;p.data.role='admin';
 p.data.members=[{id:'m1',role:'editor'}];
 assert.equal(p.data.profileOpen,false);assert.equal(p.data.memberOpenId,null);
 p.toggleProfile();assert.equal(p.data.profileOpen,true);
 p.toggleMember({currentTarget:{dataset:{id:'m1'}}});assert.equal(p.data.memberOpenId,'m1');
 p.toggleMember({currentTarget:{dataset:{id:'m1'}}});assert.equal(p.data.memberOpenId,null);
 p.data.role='viewer';p.toggleMember({currentTarget:{dataset:{id:'m1'}}});assert.equal(p.data.memberOpenId,null);
});
test('sole administrator does not expose a member action that cannot succeed',()=>{
 const {p}=harness('family-detail');p.data.ready=true;p.data.role='admin';
 p.data.members=[{id:'self',role:'admin',isSelf:true,status:'active'}];
 p.toggleMember({currentTarget:{dataset:{id:'self'}}});
 assert.equal(p.data.memberOpenId,null);
});
test('wardrobe only uses first-item onboarding for an unfiltered empty closet',()=>{
 const {p}=harness('wardrobe');
 assert.equal(p.emptyClosetFor(0),true);
 p.data.categoryKey='top';assert.equal(p.emptyClosetFor(0),false);
 p.data.categoryKey='';p.data.stateIndex=1;assert.equal(p.emptyClosetFor(0),false);
 assert.equal(p.emptyClosetFor(2),false);
});
test('a newer same-context read wins over an older read',async()=>{
 const {p}=harness('families');let finishFirst,finishSecond;
 const first=p.run(async valid=>{await new Promise(r=>finishFirst=r);if(valid())p.setData({result:'first'});});
 const second=p.run(async valid=>{await new Promise(r=>finishSecond=r);if(valid())p.setData({result:'second'});});
 finishSecond();await second;finishFirst();await first;
 assert.equal(p.data.result,'second');
});
test('family entry is inert while loading or submitting',()=>{
 const {p,nav}=harness('families');
 p.open({currentTarget:{dataset:{id:'11'}}});
 p.data.ready=true;p.data.busy=true;
 p.open({currentTarget:{dataset:{id:'11'}}});
 assert.deepEqual(nav,[]);
});
test('my opens one family directly and multiple families through switch list',()=>{
 const {p,nav}=harness('my');p.data.ready=true;p.data.families=[{id:'10'}];
 p.families();assert.equal(nav.at(-1),'/pages/family-detail/family-detail?id=10');
 p.data.families=[{id:'10'},{id:'20'}];p.families();
 assert.equal(nav.at(-1),'/pages/families/families');
});
test('my logout clears local session and returns to login instead of first-child setup',async()=>{
 const {p,runtime,nav}=harness('my');await p.logout();
 assert.equal(runtime.session.token(),undefined);
 assert.equal(nav.at(-1),'/pages/login/login');
});
test('family list keeps creation in a separate form state',()=>{
 const {p,nav}=harness('families');p.data.ready=true;p.data.families=[{id:'10'}];
 p.newFamily();assert.equal(p.data.mode,'create');assert.equal(p.data.families.length,1);
 p.cancelCreate();assert.equal(p.data.mode,'list');
 p.open({currentTarget:{dataset:{id:'10'}}});assert.equal(nav.at(-1),'/pages/home/home');
});
test('failed create preserves input and retries same idempotency key, double tap sends once',async()=>{
 const {p,requests,reply}=harness('families');
 p.data.form={name:'Family',city:'City'};const first=p.create();p.create();
 assert.equal(requests.length,1);const key=requests[0].header['Idempotency-Key'];
 requests.shift().fail({});await first;
 assert.deepEqual(p.data.form,{name:'Family',city:'City'});assert.equal(p.data.busy,false);
 const second=p.create();assert.equal(requests[0].header['Idempotency-Key'],key);
 reply({id:'10'},201);await second;
});
test('invitation previews after login without joining until explicit accept',async()=>{
 const {p,requests,reply,nav}=harness('invitation');
 p.onLoad({token:'invite'});const preview=p.reload();
 assert.equal(requests[0].url.endsWith('/invitations/preview'),true);
 reply({family_name:'Family',role:'viewer',expires_at:'2026-10-01'});await preview;
 assert.equal(requests.length,0);
 const accept=p.accept();assert.equal(requests[0].url.endsWith('/invitations/accept'),true);
 reply({family_id:'11',membership:{role:'viewer'}});await accept;
 assert.equal(nav.at(-1),'/pages/home/home');
});
test('city result requires explicit confirmation and network failure keeps manual city',async()=>{
 const {p,requests,reply,nav,runtime}=harness('location');
 p.inputCity({detail:{value:'杭州'}});const search=p.search();
 assert.ok(requests[0].url.includes('/location/search'));
 reply([{name:'杭州市',region:'浙江省'}]);await search;
 p.choose({currentTarget:{dataset:{city:'杭州市'}}});
 assert.equal(nav.length,0);assert.equal(p.data.selectedCity,'杭州市');
 p.confirmCity();assert.equal(nav.at(-1),'back');assert.equal(runtime.session.read('_','location').city,'杭州市');
 p.inputCity({detail:{value:'成都'}});const failed=p.search();requests.shift().fail({});await failed;
 assert.equal(p.data.city,'成都');p.confirmCity();assert.equal(runtime.session.read('_','location').city,'成都');
});
test('expired invitation disables acceptance without logging out or clearing other family',async()=>{
 const {p,requests,reply,runtime}=harness('invitation');runtime.session.write('10','children',[{id:'2'}]);
 p.onLoad({token:'expired'});const preview=p.reload();
 reply({error:{code:'INVITATION_UNAVAILABLE',message:'邀请已过期'}},410);await preview;
 assert.equal(p.data.unavailable,true);assert.equal(p.data.ready,false);
 p.accept();assert.equal(requests.length,0);assert.equal(runtime.session.token(),'t');
 assert.deepEqual(runtime.session.read('10','children'),[{id:'2'}]);
});
test('viewer child page cannot submit creates or archive',async()=>{
 const {p,requests}=harness('child-edit');
 p.data.ready=true;p.data.role='viewer';p.childId='2';
 await p.save();await p.archive();await p.saveMeasurement();assert.equal(requests.length,0);
});
test('version conflict preserves child draft and current expected version',async()=>{
 const {p,requests,reply}=harness('child-edit');
 p.childId='2';p.familyId='10';p.data.ready=true;p.data.role='editor';p.data.version=4;
 p.data.form={nickname:'Draft',birthday:'2024-01-01',skin_tone:''};
 const save=p.save();assert.equal(requests[0].data.expected_version,4);
 reply({error:{code:'VERSION_CONFLICT',message:'Conflict'}},409);await save;
 assert.equal(p.data.form.nickname,'Draft');assert.equal(p.data.version,4);assert.equal(p.data.conflict,true);
 assert.equal(p.data.conflictSheet,true);
});
test('archive requires its own confirmation and returns to role-aware home',async()=>{
 const {p,requests,reply,nav}=harness('child-edit');
 p.childId='2';p.familyId='10';p.data.ready=true;p.data.role='editor';p.data.version=3;
 p.archive();await tick();assert.equal(p.data.archiveSheet,true);assert.equal(requests.length,0);
 const pending=p.confirmArchive();assert.equal(requests[0].method,'DELETE');
 reply(undefined,204);await pending;
 assert.equal(p.data.archiveSheet,false);
 assert.equal(nav.at(-1),'/pages/home/home');
});
test('archive conflict closes confirmation and opens the visible conflict sheet',async()=>{
 const {p,requests,reply}=harness('child-edit');p.childId='2';p.familyId='10';p.data.ready=true;p.data.role='editor';p.data.version=3;
 p.archive();const pending=p.confirmArchive();assert.equal(requests[0].method,'DELETE');
 reply({error:{code:'VERSION_CONFLICT',message:'Conflict'}},409);await pending;
 assert.equal(p.data.archiveSheet,false);assert.equal(p.data.conflictSheet,true);
});
test('child lists are plain arrays and missing selected id falls back to first',async()=>{
 const {p,runtime,requests,reply}=harness('children');
 p.familyId='10';runtime.session.write('10','child','removed');
 const load=p.reload();reply({id:'10',name:'Family'});await tick();
 reply([{id:'m1',user_id:'1',role:'editor',status:'active'}]);await tick();
 assert.ok(requests[0].url.endsWith('/children'));
 reply([{id:'2',nickname:'Child',birthday:'2024-01-01',latest_measurement:{height_cm:null,weight_kg:12}}]);await load;
 assert.equal(p.data.currentChildId,'2');assert.equal(p.data.children[0].heightLabel,'未知');
 assert.equal(runtime.session.read('10','child'),'2');
});
test('measurement retry retains nullable values and key without resaving basic details',async()=>{
 const {p,requests,reply}=harness('child-edit');p.childId='2';p.familyId='10';p.data.ready=true;p.data.role='editor';
 p.data.form={nickname:'Unsaved',height_cm:'90',weight_kg:'',measured_on:'2026-01-01'};
 const first=p.saveMeasurement();const key=requests[0].header['Idempotency-Key'];
 assert.equal(requests[0].data.weight_kg,null);requests.shift().fail({});await first;
 assert.equal(p.data.form.height_cm,'90');const second=p.saveMeasurement();
 assert.equal(requests[0].header['Idempotency-Key'],key);reply({id:'3'});await tick();
 assert.equal(requests[0].method,'GET');reply({latest_measurement:{height_cm:90,weight_kg:null,measured_on:'2026-01-01'}});await second;
 assert.equal(p.data.form.nickname,'Unsaved');assert.equal(p.data.form.height_cm,'');
});
test('personal profile starts at version zero and settings target member string id',async()=>{
 const {p,requests,reply,runtime}=harness('preferences');p.familyId='10';p.childId='2';p.data.ready=true;p.data.role='editor';runtime.session.capability('10','editor');
 p.data.profiles={family:{styles:[],version:1},me:{styles:[],version:0}};p.data.profileTab='me';p.data.selectedStyles=['sporty'];
 const save=p.saveProfile();assert.equal(requests[0].data.expected_version,0);assert.ok(requests[0].url.endsWith('/profiles/me'));
 reply({styles:['sporty'],version:1});await save;
 p.data.form={mode:'designated_member',designated_member_id:'9007199254740993',thermal_preference:'unknown',fit_preference:'loose',avoid_high_neck:null,version:2};
 const settings=p.saveSettings();assert.equal(requests[0].data.designated_member_id,'9007199254740993');assert.equal(requests[0].data.expected_version,2);
 reply({...p.data.form,version:3});await settings;assert.equal(p.data.form.version,3);
});
test('confirmation from an old family cannot approve a mutation in a new context',async()=>{
 const {platform,runtime}=harness('family-detail');let answer;
 platform.showModal=o=>answer=o;
 const promise=require('../services/page').confirmation('Remove','Confirm');
 runtime.context.select({familyId:'20'});answer.success({confirm:true});
 assert.equal(await promise,false);
});
test('hidden pages cannot apply late data or show errors',async()=>{
 const {p}=harness('families');let done;
 const pending=p.run(async valid=>{await new Promise(r=>done=r);if(valid())p.setData({result:'late'});});
 p.onHide();done();await pending;assert.equal(p.data.result,undefined);
});

test('API rejects PATCH before calling the platform',async()=>{
 const {runtime,requests}=harness('children');
 await assert.rejects(runtime.api.request('/families/10',{method:'PATCH'}),e=>e.code==='UNSUPPORTED_METHOD');
 assert.equal(requests.length,0);
});
test('family and member edits use PUT',async()=>{
 const {p,requests,reply}=harness('family-detail');p.familyId='10';p.data.ready=true;p.data.role='admin';p.data.family={version:2};
 const save=p.save();assert.equal(requests[0].method,'PUT');reply({error:{message:'conflict'}},409);await save;
 p.data.conflict=false;p.data.members=[{id:'9007199254740993',role:'viewer',nickname:'A'}];
 p.changeRole({currentTarget:{dataset:{id:'9007199254740993'}},detail:{value:'1'}});
 assert.equal(requests.length,0);assert.equal(p.data.pendingAction.type,'role');
 const change=p.confirmAction();assert.equal(requests[0].method,'PUT');
 reply({error:{message:'conflict'}},409);await change;
});
test('family save uses its response without a second read hiding the form',async()=>{
 const {p,requests,reply}=harness('family-detail');p.familyId='10';p.data.ready=true;p.data.role='admin';
 p.data.family={id:'10',version:2};p.data.form={name:'新家',city:'杭州',timezone:'Asia/Shanghai'};
 const pending=p.save();assert.equal(requests[0].method,'PUT');
 reply({id:'10',name:'新家',city:'杭州',timezone:'Asia/Shanghai',version:3});await tick();
 const extra=requests.length;
 if(extra){reply({id:'10',name:'新家',city:'杭州',timezone:'Asia/Shanghai',version:3});await tick();if(requests.length)reply([{id:'self',user_id:'1',role:'admin',status:'active'}]);}
 await pending;
 assert.equal(extra,0);assert.equal(p.data.ready,true);assert.equal(p.data.family.version,3);
});
test('last admin cannot leave or downgrade and viewer cannot manage members',()=>{
 const {p,requests}=harness('family-detail');p.familyId='10';p.data.ready=true;p.data.role='admin';
 p.data.members=[{id:'self',user_id:'1',role:'admin',isSelf:true,nickname:'我'}];
 p.leave();assert.equal(p.data.pendingAction,null);assert.match(p.data.actionError,/管理员/);
 p.changeRole({currentTarget:{dataset:{id:'self'}},detail:{value:'1'}});
 assert.equal(p.data.pendingAction,null);assert.equal(requests.length,0);
 p.data.role='viewer';p.data.actionError='';
 p.remove({currentTarget:{dataset:{id:'other'}}});assert.equal(p.data.pendingAction,null);
});
test('removing a member requires an in-page confirmation before DELETE',async()=>{
 const {p,requests,reply}=harness('family-detail');p.familyId='10';p.data.ready=true;p.data.role='admin';p.data.family={version:2};
 p.data.members=[{id:'self',user_id:'1',role:'admin',isSelf:true},{id:'other',role:'editor',nickname:'家人'}];
 p.remove({currentTarget:{dataset:{id:'other'}}});assert.equal(requests.length,0);
 assert.equal(p.data.pendingAction.type,'remove');
 const pending=p.confirmAction();assert.equal(requests[0].method,'DELETE');
 reply({error:{message:'conflict'}},409);await pending;
});
test('viewer cannot create or revoke an invitation',()=>{
 const {p,requests}=harness('family-detail');p.familyId='10';p.data.ready=true;p.data.role='viewer';
 p.data.invitation={invitation_id:'x'};p.createInvitation();p.revoke();
 assert.equal(requests.length,0);
});
test('my page skips a child request for a family no longer accessible',async()=>{
 const {p,runtime,requests,reply}=harness('my');runtime.session.write('_','family','10');
 p.data.ready=true;p.data.child={id:'private'};
 const pending=p.reload();assert.equal(p.data.ready,false);assert.equal(p.data.child,null);
 reply({user:{id:'1'},families:[{id:'20'}]});await tick();
 const oldRequest=requests.some(r=>r.url.includes('/families/10/children'));
 if(requests.length)reply([]);await pending;
 assert.equal(oldRequest,false);assert.equal(p.data.child,null);
 assert.equal(p.data.loading,false);
});
function seedFamily(h) {
 h.p.familyId='10';h.runtime.session.write('10','children',[{id:'2'}]);h.runtime.session.write('10','child','2');
 h.runtime.session.write('10','mutation:test',{secret:true});h.runtime.session.write('100','children',[{id:'other'}]);
 h.runtime.session.write('_','families',[{id:'10'},{id:'100'}]);
 h.p.setData({children:[{id:'2'}],family:{id:'10'},currentChildId:'2',hasCache:true,cached:true});
}
test('revoked family clears only its cache and displayed children, preserving login and other families',async()=>{
 const h=harness('children');seedFamily(h);const load=h.p.reload();h.reply({error:{message:'missing'}},404);await load;
 assert.deepEqual(h.p.data.children,[]);assert.equal(h.p.data.family,null);assert.equal(h.p.data.currentChildId,null);
 assert.equal(h.p.data.hasCache,false);assert.equal(h.p.data.cached,false);assert.equal(h.p.data.ready,false);assert.equal(h.p.data.loading,false);
 assert.equal(h.runtime.session.read('10','children'),undefined);assert.equal(h.runtime.session.read('10','mutation:test'),undefined);
 assert.deepEqual(h.runtime.session.read('100','children'),[{id:'other'}]);assert.equal(h.runtime.session.token(),'t');
 assert.deepEqual(h.runtime.session.read('_','families'),[{id:'100'}]);assert.equal(h.runtime.session.read('_','family'),undefined);
});
test('missing child probes membership and does not evict an accessible family',async()=>{
 const h=harness('child-edit');seedFamily(h);h.p.childId='missing';
 const load=h.p.reload();h.reply([{id:'m',user_id:'1',role:'editor',status:'active'}]);await tick();
 h.reply({error:{message:'child missing'}},404);await tick();
 assert.ok(h.requests[0].url.endsWith('/families/10'));h.reply({id:'10'});await load;
 assert.deepEqual(h.runtime.session.read('10','children'),[{id:'2'}]);assert.equal(h.runtime.session.token(),'t');
});
test('nested 404 confirmed revoked resets child draft and family cache',async()=>{
 const h=harness('child-edit');seedFamily(h);h.p.childId='2';h.p.data.form.nickname='Private';
 const load=h.p.reload();h.reply({error:{message:'missing'}},404);await tick();
 assert.ok(h.requests[0].url.endsWith('/families/10'));h.reply({error:{message:'missing'}},404);await load;
 assert.equal(h.p.data.form.nickname,'宝贝');assert.equal(h.runtime.session.read('10','children'),undefined);
 assert.equal(h.runtime.session.token(),'t');
});
test('family switch during revoked-access probe cannot clear new family or its display',async()=>{
 const h=harness('child-edit');seedFamily(h);h.p.childId='2';
 const load=h.p.reload();h.reply({error:{message:'missing'}},404);await tick();assert.equal(h.requests.length,1);
 require('../services/page').selectFamily('100');h.p.familyId='100';h.p.data.form.nickname='Other';
 h.reply({error:{message:'missing'}},404);await load;
 assert.equal(h.p.data.form.nickname,'Other');assert.deepEqual(h.runtime.session.read('100','children'),[{id:'other'}]);
 assert.deepEqual(h.runtime.session.read('10','children'),[{id:'2'}]);
});
test('historical measurement save reads authoritative latest without overwriting basic draft',async()=>{
 const h=harness('child-edit');const p=h.p;p.familyId='10';p.childId='2';p.data.ready=true;p.data.role='editor';
 p.data.form={nickname:'Draft',height_cm:'80',weight_kg:'',measured_on:'2025-01-01'};
 const save=p.saveMeasurement();h.reply({id:'old',height_cm:80,measured_on:'2025-01-01'});await tick();
 assert.equal(h.requests[0].method,'GET');assert.ok(h.requests[0].url.endsWith('/children/2'));
 h.reply({latest_measurement:{id:'new',height_cm:100,weight_kg:null,measured_on:'2026-01-01'}});await save;
 assert.equal(p.data.latestMeasurement.id,'new');assert.equal(p.data.latestMeasurement.heightLabel,'100 cm');
 assert.equal(p.data.latestMeasurement.weightLabel,'未知');assert.equal(p.data.form.nickname,'Draft');
});
function preferences(h) {
 const p=h.p;p.familyId='10';p.childId='2';p.data.ready=true;p.data.role='viewer';
 p.data.members=[{id:'A',label:'A'},{id:'9007199254740993',label:'B'}];
 p.data.profiles={family:{styles:[],version:1},me:{styles:['sporty'],version:2}};
 return p;
}
test('designated B to family to designated keeps picker and payload synchronized',()=>{
 const h=harness('preferences');const p=preferences(h);p.data.memberIndex=1;p.data.form.designated_member_id='9007199254740993';
 p.option({currentTarget:{dataset:{name:'mode'}},detail:{value:'0'}});
 p.option({currentTarget:{dataset:{name:'mode'}},detail:{value:'1'}});
 assert.equal(p.data.form.designated_member_id,p.data.members[p.data.memberIndex].id);
});
test('viewer can read selected member profile with opaque id and cannot write it',async()=>{
 const h=harness('preferences');const p=preferences(h);
 p.applySettings({...p.data.form,mode:'designated_member',designated_member_id:'9007199254740993'});
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].method,'GET');assert.ok(h.requests[0].url.endsWith('/profiles/members/9007199254740993'));
 h.reply({styles:['clean_daily'],version:7});await tick();
 assert.deepEqual(p.data.memberPreview,{styles:['clean_daily'],version:7});assert.equal(p.data.previewMemberId,'9007199254740993');
 await p.saveProfile();assert.equal(h.requests.length,0);
 p.data.role='editor';p.data.profileTab='members/9007199254740993';await p.saveProfile();assert.equal(h.requests.length,0);
 assert.deepEqual(p.data.profiles.me,{styles:['sporty'],version:2});
});
test('member preview ignores older selection and clears when leaving designated mode',async()=>{
 const h=harness('preferences');const p=preferences(h);p.data.form.mode='designated_member';
 p.member({detail:{value:'0'}});assert.equal(h.requests.length,1);const old=h.requests.shift();
 p.member({detail:{value:'1'}});assert.equal(p.data.memberPreview,null);
 h.reply({styles:['sporty'],version:2});await tick();old.success({statusCode:200,data:{styles:['clean_daily'],version:1}});await tick();
 assert.deepEqual(p.data.memberPreview,{styles:['sporty'],version:2});
 p.member({detail:{value:'0'}});const late=h.requests.shift();
 p.option({currentTarget:{dataset:{name:'mode'}},detail:{value:'0'}});
 late.success({statusCode:200,data:{styles:['clean_daily'],version:1}});await tick();
 assert.equal(p.data.memberPreview,null);assert.equal(p.data.previewMemberId,null);assert.equal(p.data.previewLoading,false);
});
test('hidden page discards member preview response',async()=>{
 const h=harness('preferences');const p=preferences(h);p.data.form.mode='designated_member';p.member({detail:{value:'1'}});
 assert.equal(h.requests.length,1);p.onHide();h.reply({styles:['sporty'],version:2});await tick();assert.equal(p.data.memberPreview,null);
});
test('preview is independent of page loading and preserves an existing edit conflict',async()=>{
 const h=harness('preferences');const p=preferences(h);p.data.form.mode='designated_member';p.data.conflict=true;p.data.error='Conflict';
 const preview=p.member({detail:{value:'1'}});
 assert.equal(p.data.conflict,true);assert.equal(p.data.error,'Conflict');assert.equal(p.data.loading,false);
 h.reply({styles:[],version:0});await preview;assert.equal(p.data.conflict,true);
});
test('missing profile with accessible family clears preview, not family cache',async()=>{
 const h=harness('preferences');seedFamily(h);const p=preferences(h);p.data.form.mode='designated_member';
 p.member({detail:{value:'1'}});h.reply({styles:['sporty'],version:1});await tick();
 p.member({detail:{value:'0'}});assert.equal(p.data.memberPreview,null);
 h.reply({error:{message:'Profile missing'}},404);await tick();assert.equal(h.requests.length,1);h.reply({id:'10'});await tick();
 assert.equal(p.data.memberPreview,null);assert.equal(p.data.previewError,'Profile missing');assert.equal(p.data.previewLoading,false);
 assert.deepEqual(h.runtime.session.read('10','children'),[{id:'2'}]);
});
test('late preview error cannot replace a newer selected profile',async()=>{
 const h=harness('preferences');const p=preferences(h);p.data.form.mode='designated_member';
 p.member({detail:{value:'0'}});const old=h.requests.shift();p.member({detail:{value:'1'}});
 h.reply({styles:['sporty'],version:2});await tick();old.fail({});await tick();
 assert.equal(p.data.previewError,'');assert.deepEqual(p.data.memberPreview,{styles:['sporty'],version:2});
});
test('preview response after account switch is discarded',async()=>{
 const h=harness('preferences');const p=preferences(h);p.data.form.mode='designated_member';p.member({detail:{value:'1'}});
 h.runtime.session.set({token:'new',user:{id:'2'}});h.reply({styles:['sporty'],version:2});await tick();
 assert.equal(p.data.memberPreview,null);assert.equal(h.runtime.session.token(),'new');
});
test('revoked access from member preview clears profiles and selected child',async()=>{
 const h=harness('preferences');seedFamily(h);const p=preferences(h);p.data.child={nickname:'Private'};p.data.form.mode='designated_member';
 const preview=p.member({detail:{value:'1'}});h.reply({error:{message:'missing'}},404);await tick();h.reply({error:{message:'missing'}},404);await preview;
 assert.equal(p.data.child,null);assert.equal(p.data.profiles,null);assert.deepEqual(p.data.members,[]);assert.equal(p.data.memberPreview,null);
 assert.equal(h.runtime.session.read('10','children'),undefined);assert.equal(h.runtime.session.token(),'t');
});
test('failed membership probe cannot evict family data',async()=>{
 const h=harness('child-edit');seedFamily(h);h.p.childId='2';const load=h.p.reload();
 h.reply({error:{message:'missing'}},404);await tick();assert.equal(h.requests.length,1);h.requests.shift().fail({});await load;
 assert.deepEqual(h.runtime.session.read('10','children'),[{id:'2'}]);assert.equal(h.runtime.session.read('_','family'),'10');
});
test('revocation invalidates an earlier successful response before it can restore cache',async()=>{
 const h=harness('children');seedFamily(h);
 const stale=h.runtime.api.request('/families/10/children').catch(e=>e);const old=h.requests.shift();
 const load=h.p.reload();h.reply({error:{message:'missing'}},404);await load;
 old.success({statusCode:200,data:[{id:'2'}]});assert.equal((await stale).code,'STALE');
 assert.deepEqual(h.p.data.children,[]);assert.equal(h.runtime.session.read('10','children'),undefined);
});
test('failed latest refresh never replaces latest with the historical POST record or duplicates save',async()=>{
 const h=harness('child-edit');const p=h.p;p.familyId='10';p.childId='2';p.data.ready=true;p.data.role='editor';
 p.data.latestMeasurement={id:'latest'};p.data.form={height_cm:'80',weight_kg:'',measured_on:'2025-01-01'};
 const save=p.saveMeasurement();h.reply({id:'historical'});await tick();assert.equal(h.requests.length,1);h.requests.shift().fail({});await save;
 assert.equal(p.data.latestMeasurement.id,'latest');assert.equal(p.data.measurementSaved,true);assert.equal(p.data.form.height_cm,'');
 await p.saveMeasurement();assert.equal(h.requests.length,0);
});

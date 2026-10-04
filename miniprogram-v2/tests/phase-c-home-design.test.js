const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');
function harness(){
 const root=path.resolve(__dirname,'..');for(const key of Object.keys(require.cache))if(key.startsWith(root+'/services/')||key.startsWith(root+'/pages/')||key.startsWith(root+'/stores/'))delete require.cache[key];
 const platform=storage(),nav=[];Object.assign(platform,{request(){},navigateTo:o=>nav.push(o.url),reLaunch:o=>nav.push(o.url),showModal:o=>o.success({confirm:false}),showToast(){},getLocation:o=>o.fail({})});global.wx=platform;
 let def;global.Page=d=>def=d;require('../pages/home/home');delete global.Page;
 const p={...def,data:structuredClone(def.data),setData(v){Object.assign(this.data,v);}},rt=require('../services/runtime').getRuntime();
 rt.session.set({token:'t',user:{id:'u',nickname:'妈妈'}});require('../services/page').selectFamily('f');require('../services/page').selectChild('c');rt.session.capability('f','editor');p.familyId='f';p._visible=true;p.data.ready=true;p.data.writable=true;p.data.child={id:'c',nickname:'朵朵'};p.data.children=[p.data.child,{id:'d',nickname:'弟弟'}];p.data.members=[{id:'m',nickname:'爸爸',status:'active'}];
 return {p,rt,nav,v:require('../services/outfit-view')};
}
const tap=id=>({currentTarget:{dataset:{id}}});
test('context labels identify original child and specified caregiver without exposing IDs',()=>{
 const {p,v}=harness();p._outfitContext={child:{id:'c',nickname:'朵朵'}};
 const labels=v.contextLabels(p,{child_id:'d',target_date:'2026-10-04',scene:'outdoor',preference_subject:{mode:'designated_member',membership_id:'m'}});
 assert.equal(labels.childNickname,'弟弟');assert.equal(labels.sceneLabel,'户外');assert.equal(labels.preferenceLabel,'爸爸的偏好');assert.equal(labels.targetDateLabel,'10月4日 周日');
 assert.equal(v.contextLabels(p,{child_id:'unknown'}).childNickname,'当前宝贝');
});
test('refresh shows real actual dates and nickname from authoritative child profile',async()=>{
 const {p,rt,v}=harness();p.data.targetDate='';rt.outfits.context=async()=>({child:{id:'c',nickname:'朵朵',age_months:30,age_recorded_on:'2026-10-03'},today:'2026-10-03',target_date:'2026-10-04',role:'editor',preference_subject:{mode:'designated_member',membership_id:'m',owner_key:'member:m'},plans:[],weather:{status:'unknown'}});
 await v.refreshContext(p,{basisOverride:{scene:'outdoor',preference_mode:'designated_member',designated_member_id:'m'}});
 assert.equal(p.data.childNickname,'朵朵');assert.equal(p.data.childAge,'2岁6个月');assert.equal(p.data.todayLabel,'10月3日 周六');assert.equal(p.data.tomorrowLabel,'10月4日 周日');assert.equal(p.data.preferenceLabel,'爸爸的偏好');
});
test('current unavailable clothes are annotated without changing saved snapshot versions',()=>{
 const {v}=harness();const d={main_items:[{id:'a',name:'白上衣',version:1,state:'ready',fit:'fit',asset_id:'same'},{id:'b',name:'蓝裤子',asset_id:'same'}],backup:{mode:'none',items:[]},locked_ids:['a']};
 const view=v.draftView(d,[{id:'a',version:2,state:'washing',fit:'unknown',eligible:false,eligibility_reason:'合身需核对'}]);
 assert.equal(view.main_items[0].state,'ready');assert.equal(view.main_items[0].expected_version,1);assert.equal(view.main_items[0].currentStateLabel,'待洗');assert.equal(view.main_items[0].currentFitLabel,'暂不清楚');assert.ok(view.main_items[0].currentIssue);assert.match(view.main_items[0].photoNote,/同一张原图/);assert.equal(view.lockedLabel,'白上衣');
});
test('nonempty restored drafts show latest suitability warnings rather than silently clearing them',async()=>{
 const {p,rt}=harness();p.data.targetDate='2026-10-03';rt.outfitStore.open('f','c',p.data.targetDate);rt.outfitStore.patch({main_items:[{id:'a',name:'上衣',version:1,state:'ready',fit:'fit'}]});
 rt.outfits.context=async()=>({child:p.data.child,target_date:p.data.targetDate,today:p.data.targetDate,role:'editor',weather:{status:'unknown'},plans:[],garments:[{id:'a',name:'上衣',state:'washing',fit:'fit',eligible:false}],preference_subject:{mode:'family',owner_key:'family'}});
 await p.loadWeather();assert.ok(p.data.warnings.some(x=>/上衣/.test(x)));assert.equal(p.data.draft.main_items[0].currentStateLabel,'待洗');assert.equal(rt.outfitStore.get().main_items[0].version,1);
});
test('switch sheet fetches today selected summaries even while preparing tomorrow without switching child',async()=>{
 const {p,rt}=harness();p.data.mode='tomorrow';p.data.today='2026-10-03';const queries=[];
 rt.outfits.context=async(f,q)=>{queries.push(q);return {target_date:q.target_date,plans:q.child_id==='d'?[{id:'p'}]:[]};};
 await p.openChildSwitch();assert.equal(p.data.children[0].todaySummary,'今天待选');assert.equal(p.data.children[1].todaySummary,'今天已选 · 1套');assert.ok(queries.every(q=>q.target_date==='2026-10-03'));assert.equal(rt.session.read('f','child'),'c');
});
test('late today summaries cannot repopulate a dismissed or different-child sheet',async()=>{
 const {p,rt}=harness();p.data.today='2026-10-03';const resolves=[];rt.outfits.context=()=>new Promise(r=>resolves.push(r));const work=p.openChildSwitch();p.closeChildSwitch();p.data.children=[{id:'new',nickname:'新宝贝'}];for(const r of resolves)r({plans:[{id:'old'}]});await work;assert.equal(p.data.children[0].todaySummary,undefined);
});
test('plan list shows original photos and clothing summary without altering plan snapshots',async()=>{
 const {p,rt}=harness();const plan={id:'p',sequence:2,version:4,selected_by:'爸爸',main_items:[{id:'a',name:'白上衣',asset_id:'photo'}],backup:{mode:'none',items:[]},updated_at:'2026-10-03T10:00:00Z'};p.data.plans=[plan];rt.media.image=async()=>'/tmp/real-photo.png';await p.planSummaries();
 assert.equal(p.data.planViews[0].mainSummary,'白上衣');assert.equal(p.data.planViews[0].photoItems[0].image,'/tmp/real-photo.png');assert.match(p.data.planViews[0].updatedLabel,/更新/);assert.equal(plan.main_items[0].image,undefined);
});
test('unselected item opens precise operation entry while selected item only previews original',async()=>{
 const {p,rt,nav}=harness();p.data.targetDate='2026-10-03';p.data.draft={main_items:[{id:'a',asset_id:'photo'}]};p.openItem(tap('a'));assert.match(nav[0],/item=a&usage=main/);p.data.viewSelected=true;let previewed=0;rt.media.preview=async()=>previewed++;await p.openItem(tap('a'));assert.equal(nav.length,1);assert.equal(previewed,1);
});
test('identity reset removes caregiver and original success presentation immediately',()=>{
 const {p,rt,v}=harness();v.bindPage(p);p.setData({childNickname:'旧宝贝',reviewSnapshot:{id:'private'},reviewIdentity:{name:'private'},packingItems:[{name:'private'}],planViews:[{id:'private'}]});rt.session.set({token:'new',user:{id:'other'}});require('../services/page').selectFamily('g');require('../services/page').selectChild('e');v.bindPage(p);assert.equal(p.data.childNickname,'');assert.equal(p.data.reviewSnapshot,null);assert.equal(p.data.reviewIdentity,null);assert.deepEqual(p.data.packingItems,[]);assert.deepEqual(p.data.planViews,[]);
});
test('C input changes report real cause and only a plan revision conflict offers family comparison',async()=>{
 const {p}=harness();await p.run(()=>{throw Object.assign(new Error('衣物资料已变化，请重新核对'),{status:409,code:'GARMENT_CHANGED'});},true);assert.equal(p.data.conflict,false);assert.match(p.data.error,/衣物资料/);await p.run(()=>{throw Object.assign(new Error('家人已修改这套'),{status:409,code:'VERSION_CONFLICT'});},true);assert.equal(p.data.conflict,true);
});
test('new criteria from an explicitly displayed selected plan start from its frozen basis',()=>{
 const {p,rt}=harness();rt.outfitStore.open('f','c','2026-10-03',{scene:'daily',preference_mode:'family'});p.setData({viewSelected:true,selectedPlan:{scene:'formal',preference_subject:{mode:'designated_member',membership_id:'m'}}});p.criteria();assert.equal(p.data.sceneIndex,3);assert.equal(p.data.preferenceIndex,2);assert.equal(p.data.memberIndex,0);
});
test('starting a reload clears old member overlays and rejects late plan photos',async()=>{
 const {p,rt}=harness();p._outfitContext={child:{id:'c',nickname:'旧宝贝'}};p.setData({criteriaSheet:true,unknownResult:true,plans:[{id:'old',main_items:[{id:'a',asset_id:'old-photo'}],backup:{mode:'none',items:[]}}]});
 let release;rt.media.image=()=>new Promise(r=>release=r);const photo=p.planSummaries();p.run=()=>Promise.resolve();await p.reload();release('/tmp/old.png');await photo;
 assert.deepEqual(p.data.planViews,[]);assert.equal(p.data.criteriaSheet,false);assert.deepEqual(p.data.members,[]);assert.equal(p._outfitContext,null);assert.equal(p.data.unknownResult,false);
});
test('signed-out homepage removes private content before redirecting',()=>{
 const {p,rt,nav}=harness();p.setData({draft:{main_items:[{image:'/tmp/private.png'}]},criteriaSheet:true,ready:true,planViews:[{id:'private'}]});rt.session.logout();p.onShow();assert.equal(p.data.ready,false);assert.equal(p.data.draft,null);assert.equal(p.data.criteriaSheet,false);assert.deepEqual(p.data.members,[]);assert.deepEqual(p.data.planViews,[]);assert.equal(nav.at(-1),'/pages/onboarding/onboarding');
});
test('today summaries remain valid when only an independent suggestion draft changes',async()=>{
 const {p,rt}=harness();p.data.today='2026-10-03';rt.outfitStore.open('f','c',p.data.today);const resolves=[];rt.outfits.context=()=>new Promise(r=>resolves.push(r));const work=p.openChildSwitch();rt.outfitStore.patch({main_items:[{id:'new-suggestion'}]});for(const r of resolves)r({plans:[{id:'selected'}]});await work;assert.ok(p.data.children.every(c=>c.todaySummary==='今天已选 · 1套'));
});
test('selected plan photo remains valid when only an independent suggestion draft changes',async()=>{
 const {p,rt}=harness();rt.outfitStore.open('f','c','2026-10-03');p.data.plans=[{id:'p',main_items:[{id:'a',asset_id:'photo'}],backup:{mode:'none',items:[]}}];let release;rt.media.image=()=>new Promise(r=>release=r);const work=p.planSummaries();rt.outfitStore.patch({main_items:[{id:'new-suggestion'}]});release('/tmp/selected.png');await work;assert.equal(p.data.planViews[0].photoItems[0].image,'/tmp/selected.png');
});
test('missing location callback cannot prevent actual date and unknown-weather context from loading',async t=>{
 const {p,rt}=harness();t.mock.timers.enable({apis:['setTimeout']});global.wx.getLocation=()=>{};let called=0;rt.outfits.context=async()=>{called++;return {child:p.data.child,target_date:'2026-10-03',today:'2026-10-03',role:'editor',weather:{status:'unknown'},plans:[],garments:[],preference_subject:{mode:'family',owner_key:'family'}};};rt.outfits.recommend=async()=>({items:[]});
 const work=p.loadWeather();t.mock.timers.tick(5000);await Promise.resolve();assert.equal(called,1);await work;assert.equal(p.data.todayLabel,'10月3日 周六');assert.equal(p.data.dailyLoading,false);assert.equal(p.data.weather.status,'unknown');
});
test('family access loss clears every private comparison and sharing draft field',()=>{
 const {p,rt,v}=harness();p.setData({latestPlan:{id:'private',main_items:[{name:'private'}]},periods:[{nickname:'private'}],sharingReason:'private',sharingId:'private',members:[{nickname:'private'}]});rt.session.clearFamily('f');v.accessRevoked(p);assert.equal(p.data.latestPlan,null);assert.deepEqual(p.data.periods,[]);assert.equal(p.data.sharingReason,'');assert.equal(p.data.sharingId,'');assert.deepEqual(p.data.members,[]);
});

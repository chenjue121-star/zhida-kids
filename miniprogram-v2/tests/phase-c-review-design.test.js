const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {storage}=require('./helpers');

function harness(){
 const root=path.resolve(__dirname,'..');
 for(const key of Object.keys(require.cache))if(['/services/','/pages/','/stores/'].some(part=>key.startsWith(root+part)))delete require.cache[key];
 const platform=storage(),nav=[];
 Object.assign(platform,{request(){},navigateTo:o=>nav.push(o.url),navigateBack:()=>nav.push('back'),reLaunch:o=>nav.push(o.url),showModal:o=>o.success({confirm:false}),getLocation:o=>o.fail({})});
 global.wx=platform;let def;global.Page=d=>def=d;require('../pages/outfit-review/outfit-review');delete global.Page;
 const p={...def,data:structuredClone(def.data),setData(v){Object.assign(this.data,v);}};
 const rt=require('../services/runtime').getRuntime(),page=require('../services/page');
 rt.session.set({token:'t',user:{id:'u',nickname:'妈妈'}});page.selectFamily('f');page.selectChild('c');rt.session.capability('f','editor');
 p.familyId='f';p._visible=true;p.data.ready=true;p.data.writable=true;p.data.targetDate='2026-10-03';
 rt.outfitStore.open('f','c',p.data.targetDate);
 rt.outfitStore.patch({main_items:[{id:'shirt',version:1,name:'米白短袖',category:'top',asset_id:'photo'}]});
 p.data.draft=rt.outfitStore.get();p.data.weather={status:'known'};
 p._outfitContext={child:{id:'c',nickname:'小豆子'},target_date:p.data.targetDate,preference_subject:{mode:'family',owner_key:'family'}};
 return {p,rt,nav,platform};
}
const tap=id=>({currentTarget:{dataset:{id}}});
const source=(plan,usage='backup')=>({plan_id:plan,child_id:'other',nickname:'小团子',sequence:plan==='one'?1:2,version:1,usage,selected_by:'爸爸',target_date:'2026-10-03'});
function sharingFixture(p,rt,resolved){
 const grant={garment_id:'shirt',reason:'上午外出，下午再用',token:'kept',periods:[{child_id:'c',start:'08:00',end:'12:00'},{child_id:'other',start:'14:00',end:'18:00'}]};
 rt.outfitStore.patch({sharing_grants:[grant]});p.data.draft=rt.outfitStore.get();
 p.data.review={valid:resolved,conflicts:[{garment_id:'shirt',usage:['main'],resolved,sources:[source('one'),source('two')]}],warnings:[],missing:[]};
 return grant;
}

test('unknown weather requires the caregiver acknowledgement even with an otherwise valid review',()=>{
 const {p}=harness();p.data.weather={status:'unknown'};p.data.review={valid:true};let submitted=0;p.performSave=()=>submitted++;
 p.save();assert.equal(submitted,0);assert.match(p.data.error,/天气|核对/);
 p.data.weatherAcknowledged=true;p.save();assert.equal(submitted,1);
});

test('unconfirmed backup staging cannot be mistaken for the confirmed backup at final save',()=>{
 const {p,rt}=harness();rt.outfitStore.stageBackup({mode:'partial',items:[{id:'spare',version:1}]});p.data.draft=rt.outfitStore.get();p.data.review={valid:true};let submitted=0;p.performSave=()=>submitted++;
 p.save();assert.equal(submitted,0);assert.match(p.data.error,/备用.*确认|备用.*暂存/);
});

test('expired sharing is not displayed or reused while every concrete source remains visible',()=>{
 const {p,rt}=harness();sharingFixture(p,rt,false);p.refreshDisplay();p.openSharing(tap('shirt'));
 assert.equal(p.data.sharingSummary.length,0);assert.equal(p.data.sharingSources.length,2);
 assert.deepEqual(p.data.periods.map(x=>[x.nickname,x.start,x.end]),[['小豆子','',''],['小团子','','']]);
 assert.equal(p.data.sharingReason,'');assert.equal(rt.outfitStore.get().sharing_grants[0].token,'kept');
});

test('preset period edits stay staged and cancel restores the confirmed schedule on reopen',()=>{
 const {p,rt}=harness();sharingFixture(p,rt,true);p.refreshDisplay();p.openSharing(tap('shirt'));
 p.choosePeriod({currentTarget:{dataset:{id:'c'}},detail:{value:'2'}});
 assert.deepEqual([p.data.periods[0].start,p.data.periods[0].end],['14:00','18:00']);assert.equal(p.data.sharingDirty,true);
 assert.equal(rt.outfitStore.get().sharing_grants[0].periods[0].start,'08:00');
 p.cancelSharing();p.openSharing(tap('shirt'));assert.equal(p.data.periods[0].start,'08:00');assert.equal(p.data.sharingReason,'上午外出，下午再用');assert.equal(p.data.sharingDirty,false);
});

test('blank reason or overlapping period cannot be confirmed and a valid form sends trimmed explicit periods',async()=>{
 const {p,rt}=harness();sharingFixture(p,rt,false);p.refreshDisplay();p.openSharing(tap('shirt'));let requests=[];
 rt.outfits.sharing=async(f,payload)=>{requests.push(payload);return {grant:{family_id:f,child_id:payload.child_id,target_date:payload.target_date,draft_id:payload.draft_id,target_plan_id:payload.target_plan_id,garment_id:'shirt',usage:['main'],sources:p.data.review.conflicts[0].sources,periods:payload.periods,reason:payload.reason,token:'new'}};};p.preflight=async()=>{};
 p.data.periods=[{child_id:'c',nickname:'小豆子',start:'08:00',end:'12:00'},{child_id:'other',nickname:'小团子',start:'08:00',end:'18:00'}];p.data.sharingReason='   ';
 await p.confirmSharing();assert.equal(requests.length,0);
 p.data.sharingReason=' 上午外出 ';await p.confirmSharing();assert.equal(requests.length,0);assert.match(p.data.error,/重叠/);
 p.data.periods[1].start='14:00';await p.confirmSharing();assert.equal(requests.length,1);assert.equal(requests[0].reason,'上午外出');assert.deepEqual(requests[0].periods,[{child_id:'c',start:'08:00',end:'12:00'},{child_id:'other',start:'14:00',end:'18:00'}]);
});

test('packing deduplicates physical identity, preserves two pieces from one image, and explains backup use',()=>{
 const {p,rt}=harness();rt.outfitStore.patch({main_items:[{id:'shirt',version:1,name:'短袖',category:'top',asset_id:'shared'},{id:'shorts',version:1,name:'短裤',category:'bottom',asset_id:'shared'},{id:'shoe',version:1,name:'蓝鞋',category:'shoes',asset_id:'shoe-image'}],backup:{mode:'full',items:[{id:'other-shirt',version:1,name:'备用短袖',category:'top',asset_id:'spare'},{id:'other-bottom',version:1,name:'备用短裤',category:'bottom',asset_id:'spare'},{id:'shoe',version:1,name:'蓝鞋',category:'shoes',asset_id:'shoe-image'}]}});
 p.data.draft=rt.outfitStore.get();p.refreshDisplay();
 assert.equal(p.data.packingItems.length,5);assert.equal(p.data.packingItems.filter(i=>i.asset_id==='shared').length,2);
 assert.equal(p.data.packingItems.find(i=>i.id==='shoe').usesLabel,'主搭配 · 备用');
 assert.match(p.data.reviewSnapshot.backup.items.find(i=>i.id==='shoe').compatibilityLabel,/沿用主搭配/);
 assert.match(p.data.reviewSnapshot.main_items[0].photoLabel,/同图/);
});

test('same-child pending display uses the rich original submission without mutating an independent basis draft',async()=>{
 const {p,rt}=harness();const original=rt.outfitStore.get(),frozen=rt.outfitStore.payload();
 rt.session.write('f','outfit-pending:2026-10-03',{operation_id:'original',payload:frozen});
 rt.outfitStore.open('f','c',p.data.targetDate,{preference_mode:'current_member',scene:'outdoor'});rt.outfitStore.patch({main_items:[{id:'independent',version:1,name:'独立偏好的草稿'}]});const separate=rt.outfitStore.get();
 rt.api.request=async()=>[{user_id:'u',status:'active',role:'editor',nickname:'妈妈'}];let checked=0;
 rt.outfits.context=async(f,q)=>{checked++;assert.equal(q.child_id,'c');return {child:{id:'c',nickname:'小豆子'},target_date:q.target_date,role:'editor',preference_subject:{mode:'family',owner_key:'family'}};};rt.outfits.review=()=>{throw new Error('must not review original again');};rt.media.image=async()=>'/original-photo';
 await p.reload();
 assert.equal(p.data.unknownResult,true);assert.equal(p.data.reviewSnapshot.main_items[0].name,'米白短袖');assert.equal(p.data.reviewIdentity.childNickname,'小豆子');assert.equal(checked,1);
 assert.equal(p.data.reviewSnapshot.draft_id,original.draft_id);assert.deepEqual(rt.outfitStore.get(),separate);assert.deepEqual(rt.outfits.pending('f',p.data.targetDate).payload,frozen);
});

test('historical completion keeps original main and backup while displaying the later family plan separately',async()=>{
 const {p,rt}=harness();const original={id:'plan',child_id:'c',target_date:p.data.targetDate,sequence:1,version:1,scene:'daily',preference_subject:{mode:'family',owner_key:'family'},main_items:[{id:'old',name:'原主搭配',version:1}],backup:{mode:'partial',items:[{id:'old-backup',name:'原备用',version:1}]}};const frozen=structuredClone(original);
 rt.outfits.context=async()=>({child:{id:'c',nickname:'小豆子'},plans:[{...original,version:2,selected_by:'爸爸',main_items:[{id:'new',name:'家人新搭配',version:1}],current_warnings:[{message:'使用前核对待洗衣物'}]}],preference_subject:{mode:'family',owner_key:'family'}});
 await p.finish({status:'completed',plan:original});await p.currentNotes(original,()=>true);
 assert.deepEqual(original,frozen);assert.deepEqual(p.data.completedPlan,frozen);assert.equal(p.data.completedView.main_items[0].name,'原主搭配');assert.equal(p.data.completedView.backup.items[0].name,'原备用');assert.equal(p.data.latestView.main_items[0].name,'家人新搭配');assert.match(p.data.currentNotes.join(' '),/后来|之后/);
});

test('late original photo cannot repopulate private completion after access changes',async()=>{
 const {p,rt}=harness();let finishImage;rt.media.image=()=>new Promise(r=>finishImage=r);p.data.completedView={id:'p',version:1,main_items:[{id:'a',asset_id:'photo'}],backup:{mode:'none',items:[]}};
 const pending=p.displayImages('completedView');rt.session.capability('f',null);p.setData({completedView:null});finishImage('/private');await pending;assert.equal(p.data.completedView,null);
});

test('editing review distinguishes retained, added and removed uses without releasing another plan',()=>{
 const {p,rt}=harness();const plan={id:'original',version:1,child_id:'c',target_date:p.data.targetDate,sequence:1,main_items:[{id:'shirt',version:1,name:'原短袖'},{id:'shoe',version:1,name:'蓝鞋'}],backup:{mode:'partial',items:[{id:'spare',version:1,name:'原备用'}]}};
 rt.outfitStore.beginEdit(plan);rt.outfitStore.patch({main_items:[{id:'new',version:1,name:'新短袖'},{id:'shoe',version:1,name:'蓝鞋'}],backup:{mode:'none',items:[]}});p.data.draft=rt.outfitStore.get();p.refreshDisplay();
 assert.deepEqual(p.data.reservationChanges.kept.map(i=>i.name),['蓝鞋']);assert.deepEqual(p.data.reservationChanges.added.map(i=>i.name),['新短袖']);assert.deepEqual(p.data.reservationChanges.removed.map(i=>i.name),['原短袖','原备用']);assert.equal(plan.main_items[0].id,'shirt');
});

test('preflight uses its authoritative weather and clears acknowledgement only when effective conditions change',async()=>{
 const {p,rt}=harness();const weather={status:'unknown',target_date:p.data.targetDate,city:'杭州',captured_at:'old'};p.data.weather=weather;rt.outfitStore.patch({weather,weather_acknowledged:true});p.data.draft=rt.outfitStore.get();p.data.weatherAcknowledged=true;
 rt.outfits.review=async()=>({valid:true,weather:{...weather,captured_at:'new'},conflicts:[],warnings:[],missing:[]});await p.preflight();assert.equal(p.data.weatherAcknowledged,true);
 rt.outfits.review=async()=>({valid:true,weather:{status:'unknown',target_date:p.data.targetDate,city:'北京'},conflicts:[],warnings:[],missing:[]});await p.preflight();assert.equal(p.data.weather.city,'北京');assert.equal(p.data.weatherUnknown,true);assert.equal(p.data.weatherAcknowledged,false);assert.equal(rt.outfitStore.get().weather_acknowledged,false);assert.equal(p.data.review,null);
});

test('a context refresh cannot silently carry acknowledgement from a previous weather basis',async()=>{
 const {p,rt}=harness();const old={status:'unknown',target_date:p.data.targetDate,city:'杭州'};rt.outfitStore.patch({weather:old,weather_acknowledged:true});p.data.draft=rt.outfitStore.get();p.data.weatherAcknowledged=true;p.data.weather={...old,city:'北京'};
 rt.outfits.review=async()=>({valid:true,weather:{...old,city:'北京'},conflicts:[],warnings:[],missing:[]});await p.preflight();assert.equal(p.data.weatherAcknowledged,false);assert.equal(p.data.review,null);
});

test('current garment issues are shown without changing the retained physical snapshot',async()=>{
 const {p,rt}=harness();const before=rt.outfitStore.get();p._outfitContext.garments=[{id:'shirt',version:2,state:'washing',fit:'fit',eligible:false,eligibility_reason:'待洗'}];rt.outfits.review=async()=>({valid:false,conflicts:[],warnings:[],missing:[{message:'米白短袖当前待洗'}]});await p.preflight();assert.match(p.data.reviewSnapshot.main_items[0].currentIssue,/待洗/);assert.deepEqual(rt.outfitStore.get(),before);
});

test('historical completion retains the exact submitted sharing arrangement as readable source facts',async()=>{
 const {p}=harness();const plan={id:'plan',version:1,sequence:1,child_id:'c',target_date:p.data.targetDate,main_items:[{id:'shirt',name:'短袖'}],backup:{mode:'none',items:[]},sharing_arrangements:[{garment_id:'shirt',reason:'上午与下午分开',sources:[source('one'),source('two')],periods:[{child_id:'c',start:'08:00',end:'12:00'},{child_id:'other',start:'14:00',end:'18:00'}]}]};
 await p.finish({status:'completed',plan});assert.equal(p.data.sharingSummary.length,1);assert.deepEqual(p.data.sharingSummary[0].periods.map(p=>p.nickname),['小豆子','小团子']);assert.equal(p.data.sharingSummary[0].reason,'上午与下午分开');
});

test('removing family access clears all comparison and staged sharing identities',()=>{
 const {p,rt}=harness();sharingFixture(p,rt,true);p.refreshDisplay();p.openSharing(tap('shirt'));p.data.latestPlan={id:'private',main_items:[{id:'private-item'}]};p._sharingScope='private';p._garmentReviewCurrent=()=>true;p._submittedDraftId='private-draft';rt.session.clearFamily('f');p.onEditRevoked();
 assert.equal(p.data.latestPlan,null);assert.deepEqual(p.data.periods,[]);assert.equal(p.data.sharingReason,'');assert.equal(p.data.sharingId,'');assert.equal(p._sharingScope,null);assert.equal(p._garmentReviewCurrent,null);assert.equal(p._submittedDraftId,null);
});

test('a new source or source revision closes the staged schedule and requires viewing all sources again',async()=>{
 const {p,rt}=harness();sharingFixture(p,rt,false);p.refreshDisplay();p.openSharing(tap('shirt'));const before=rt.outfitStore.get();let sent=0;rt.outfits.sharing=async()=>{sent++;};
 rt.outfits.review=async()=>({valid:false,conflicts:[{garment_id:'shirt',usage:['main'],resolved:false,sources:[{...source('one'),version:2},source('two'),source('three','main')]}],warnings:[],missing:[]});await p.preflight();
 assert.equal(p.data.sharingOpen,false);assert.deepEqual(p.data.sharingSources,[]);assert.match(p.data.error,/来源.*变化|重新核对/);assert.deepEqual(rt.outfitStore.get(),before);await p.confirmSharing();assert.equal(sent,0);
 p.openSharing(tap('shirt'));assert.equal(p.data.sharingSources.length,3);assert.equal(p.data.sharingSources[0].version,2);assert.equal(p.data.sharingReason,'');
});

test('a sharing response cannot authorize additional or revised sources that were never displayed',async()=>{
 const {p,rt}=harness();sharingFixture(p,rt,false);p.refreshDisplay();p.openSharing(tap('shirt'));p.data.periods=[{child_id:'c',start:'08:00',end:'12:00'},{child_id:'other',start:'14:00',end:'18:00'}];p.data.sharingReason='上午外出';const before=rt.outfitStore.get();let resolve;rt.outfits.sharing=()=>new Promise(r=>resolve=r);p.preflight=async()=>{};
 const pending=p.confirmSharing();resolve({grant:{family_id:'f',child_id:'c',target_date:p.data.targetDate,draft_id:before.draft_id,target_plan_id:null,garment_id:'shirt',usage:['main'],sources:[{...source('one'),version:2},source('two'),source('three','main')],periods:p.data.periods,reason:'上午外出',token:'unseen'}});await pending;
 assert.deepEqual(rt.outfitStore.get(),before);assert.equal(p.data.sharingOpen,false);assert.match(p.data.error,/来源.*变化|重新核对/);
});

test('confirming latest garment facts preserves an outstanding explicit backup review',async()=>{
 const {p,rt}=harness();rt.outfitStore.patch({backup_needs_review:true,backup:{mode:'none',items:[]}});p.data.draft=rt.outfitStore.get();rt.outfits.context=async()=>({garments:[{id:'shirt',version:2,name:'米白短袖',category:'top',eligible:true,state:'ready',fit:'fit'}]});rt.outfits.review=async()=>({valid:true,warnings:[],missing:[],conflicts:[]});let sent=0;p.performSave=()=>sent++;
 await p.latestGarments();await p.confirmGarments();assert.equal(rt.outfitStore.get().main_items[0].version,2);assert.equal(rt.outfitStore.get().backup_needs_review,true);assert.equal(p.data.draft.backup_needs_review,true);p.save();assert.equal(sent,0);assert.match(p.data.error,/备用/);
});

const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,confirmation,membership}=require('../../services/page');
const v=require('../../services/outfit-view');
const copy=value=>JSON.parse(JSON.stringify(value));
const periodOptions=[{label:'请选择时段',start:'',end:''},{label:'上午 08:00–12:00',start:'08:00',end:'12:00'},{label:'下午 14:00–18:00',start:'14:00',end:'18:00'},{label:'全天 08:00–18:00',start:'08:00',end:'18:00'}];
const caregiverCopy=value=>String(value || '').replace(/原操作/g,'这次保存').replace(/成功快照/g,'当时选定的内容').replace(/最新版本/g,'最新内容');
const snapshotKey=s=>JSON.stringify([s && s.id,s && s.version,s && s.draft_id,s && s.revision]);
function identity(page,d){return {...v.contextLabels(page,d),targetDate:d.target_date};}
function operationChild(page){
 const rt=getRuntime(),context=rt.context.capture().current,selected=context && String(context.familyId)===String(page.familyId)?context.childId:rt.session.read(page.familyId,'child');
 return page._pendingSnapshot && String(page._pendingSnapshot.child_id)===String(selected)?page._pendingSnapshot.child_id:selected;
}
function snapshotView(d,previous,currentGarments){
 const view=v.draftView(d,currentGarments);if(!view)return null;
 const all=[...view.main_items,...view.backup.items],photos=new Map(),images=new Map();
 if(previous && snapshotKey(previous)===snapshotKey(view))for(const i of [...previous.main_items,...previous.backup.items])if(i.image)images.set(i.asset_id,i.image);
 for(const i of all)if(i.asset_id){const ids=photos.get(i.asset_id)||new Set();ids.add(v.itemId(i));photos.set(i.asset_id,ids);}
 const itemView=i=>({...i,name:i.name || i.categoryLabel || '已提交衣物',image:i.image || images.get(i.asset_id) || '',photoLabel:i.asset_id?(photos.get(i.asset_id).size>1?'同图实物 · 原图':'原图'):'手动录入实物'});
 view.main_items=view.main_items.map(itemView);
 view.backup.items=view.backup.items.map(i=>{
  const main=view.main_items.find(x=>v.itemId(x)===String(i.replaces_garment_id)),reused=view.main_items.find(x=>v.itemId(x)===v.itemId(i));
  return {...itemView(i),compatibilityLabel:reused?'沿用主搭配，只装一件':main?'可替换 '+main.name:view.backup.mode==='full'?'整套备用组成':'按需替换对应'+i.categoryLabel};
 });
 view.backupLabel=view.backup.items.length?(view.backup.mode==='full'?'整套备用':'局部备用')+' · '+view.backup.items.length+' 件':'无备用';return view;
}
function packing(d){
 const items=new Map();for(const [usage,list] of [['主搭配',d.main_items],['备用',d.backup.items]])for(const i of list){const id=v.itemId(i),previous=items.get(id);items.set(id,{...i,usesLabel:previous?previous.usesLabel+' · '+usage:usage});}return [...items.values()];
}
function periodLabel(p){const preset=periodOptions.find(x=>x.start && x.start===p.start && x.end===p.end);return preset?preset.label:p.start && p.end?p.start+'–'+p.end:'尚未安排时段';}
function formPeriod(p){const index=periodOptions.findIndex(x=>x.start===p.start && x.end===p.end);return {...p,periodIndex:index<0?0:index,periodLabel:periodLabel(p)};}
function sourceView(s){return {...s,source_key:s.plan_id+':'+s.usage,usageLabel:s.usage==='backup'?'备用':'主搭配',periodLabel:s.arrangement && (s.arrangement.periods||[]).some(p=>String(p.child_id)===String(s.child_id))?periodLabel(s.arrangement.periods.find(p=>String(p.child_id)===String(s.child_id))):'按日安排'};}
function canonical(value){return Array.isArray(value)?value.map(canonical):value && typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;}
function sourceBinding(conflict){
 if(!conflict)return null;
 const sources=(conflict.sources||[]).map(s=>[String(s.plan_id),s.version,String(s.child_id),s.target_date,s.usage,s.selected_by_id || null,canonical(s.arrangement || null)]).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
 return JSON.stringify([String(conflict.garment_id),(conflict.usage||[]).slice().sort(),sources]);
}
function sharingScope(page,conflict){
 const draft=getRuntime().outfitStore.get();if(!draft || !conflict)return null;
 return JSON.stringify([page.familyId,draft.draft_id,draft.revision,draft.child_id,draft.target_date,draft.target_plan_id,draft.expected_version,canonical(v.location()),canonical(page._location || {}),sourceBinding(conflict),canonical(conflict.existing_arrangements || [])]);
}
function richOriginal(rt,family,payload){
 const find=d=>d && (d.draft_id===payload.draft_id?d:find(d.source_origin));
 for(const d of Object.values(rt.session.read(family,'outfit-drafts')||{})){const match=find(d);if(match)return {...copy(match),...copy(payload),main_items:copy(match.main_items),backup:copy(match.backup)};}
 return copy(payload);
}
function weatherKey(weather){return JSON.stringify(['status','target_date','city','lat','lon','temp_min','temp_max','condition','condition_code','humidity','precipitation_probability','wind_speed'].map(k=>weather && weather[k]===undefined?null:weather && weather[k]));}
function reservationChanges(d){
 if(!d.target_plan_id || !d.source_snapshot)return null;
 const uses=s=>[...(s.main_items||[]).map(i=>({...i,usageKey:v.itemId(i)+':main',usageLabel:'主搭配',usage:'main'})),...(s.backup && s.backup.items||[]).map(i=>({...i,usageKey:v.itemId(i)+':backup',usageLabel:'备用',usage:'backup'}))];
 const before=uses(d.source_snapshot),after=uses(d),key=i=>v.itemId(i)+':'+i.usage;
 return {kept:after.filter(i=>before.some(x=>key(x)===key(i))),added:after.filter(i=>!before.some(x=>key(x)===key(i))),removed:before.filter(i=>!after.some(x=>key(x)===key(i)))};
}
Page(definePage({
 data:{draft:null,review:null,writable:false,targetDate:'',members:[],unknownResult:false,completedPlan:null,completedView:null,latestView:null,reviewIdentity:null,reviewSnapshot:null,packingItems:[],reservationChanges:null,sharingSummary:[],sharingSources:[],sharingGarment:null,currentNotes:[],weatherAcknowledged:false,weatherUnknown:false,notSaved:false,sharingOpen:false,sharingDirty:false,sharingReady:false,sharingValidation:'',sharingId:'',sharingReason:'',periods:[],periodOptions:periodOptions.map(x=>x.label),latestPlan:null,plans:[],compareOpen:false,garmentReviewOpen:false,latestGarmentRows:[]},
 errorState:v.errorState,
 onLoad(o){this.data.targetDate=o.date || '';},
 onShow(){this._visible=true;const owner=this._owner;if(!v.bindPage(this))return;if(!owner || owner.user!==this._owner.user || owner.generation!==this._owner.generation || owner.family!==this._owner.family || owner.child!==this._owner.child){this._pendingSnapshot=null;this.setData({notSaved:false,reservationChanges:null,sharingGarment:null,sharingReady:false,sharingValidation:''});}return this.reload();},
 reload(){return this.run(async valid=>{
  const rt=getRuntime(),info=await membership(this.familyId);if(!valid())return;
  rt.session.capability(this.familyId,info.role);this.setData({ready:!!info.role,writable:rt.session.canEdit(this.familyId),role:info.role,members:info.members.filter(m=>m.status==='active')});
  if(!info.role){this.onEditRevoked();return;}
  const pending=rt.outfits.pending(this.familyId,this.data.targetDate,operationChild(this));
  if(pending){
   this._submittedDraftId=pending.payload.draft_id;this._pendingSnapshot=richOriginal(rt,this.familyId,pending.payload);
   this.setData({unknownResult:true,draft:snapshotView(this._pendingSnapshot),review:null});this.refreshDisplay();
   const payload=pending.payload;
   const context=await rt.outfits.context(this.familyId,{child_id:payload.child_id,target_date:payload.target_date,scene:payload.scene,preference_mode:payload.preference_mode,designated_member_id:payload.designated_member_id,...v.location(),...(this._location||{})});
   if(!valid())return;this._outfitContext=context;this.refreshDisplay();await this.displayImages('reviewSnapshot');return;
  }
  if(this.data.completedPlan){await this.currentNotes(this.data.completedPlan,valid);await this.displayImages('completedView');return;}
  if(!this.data.writable){this.refreshDisplay();return;}
  this._pendingSnapshot=null;await v.refreshContext(this,{valid});if(!valid())return;v.sync(this);this.refreshDisplay();await this.preflight();
 });},
 onHide(){this._visible=false;this._load=(this._load||0)+1;getRuntime().outfitStore.invalidate();},onUnload(){this.onHide();},
 refreshDisplay(){
  const d=this.data.completedPlan || (this.data.unknownResult?this._pendingSnapshot || this.data.draft:this.data.draft);
  if(!d){this.setData({reviewIdentity:null,reviewSnapshot:null,packingItems:[],sharingSummary:[],reservationChanges:null});return;}
  const context=this._outfitContext,live=!this.data.completedPlan && !this.data.unknownResult && context && context.child && String(context.child.id)===String(d.child_id)?context.garments:undefined;
  const snapshot=snapshotView(d,this.data.completedPlan?this.data.completedView:this.data.reviewSnapshot,live),labels=identity(this,d),review=this.data.review;
  const target=(this.data.plans||[]).find(p=>String(p.id)===String(d.target_plan_id)),sequence=d.source_sequence || target && target.sequence,edit=!!d.target_plan_id;
  labels.intentTitle=this.data.completedPlan?'这次已选好':edit?(sequence?'保存第 '+sequence+' 套修改':'保存这套修改'):'新增这套前核对';
  labels.intentLabel=edit?'修改':'新增';labels.intentNote=edit?(sequence?'只更新第 '+sequence+' 套，其他已选方案保留。':'只更新这套，其他已选方案保留。'):'新增后保留已有方案，不覆盖其他已选。';
  const weather=this.data.completedPlan?d.weather:review && review.weather || (this.data.unknownResult?d.weather || this._outfitContext && this._outfitContext.weather:this.data.weather);
  const childNames=new Map([[String(d.child_id),labels.childNickname]]);
  for(const c of review && review.conflicts || [])for(const s of c.sources || [])childNames.set(String(s.child_id),s.nickname || '另一位宝贝');
  const grants=this.data.completedPlan?d.sharing_arrangements || []:this.data.unknownResult?d.sharing_grants || []:(review && review.conflicts || []).filter(c=>c.resolved).map(c=>(d.sharing_grants||[]).find(g=>String(g.garment_id)===String(c.garment_id))).filter(Boolean);
  for(const g of grants)for(const s of g.sources || [])childNames.set(String(s.child_id),s.nickname || '另一位宝贝');
  const sharingSummary=grants.map(grant=>{
   const item=[...snapshot.main_items,...snapshot.backup.items].find(i=>v.itemId(i)===String(grant.garment_id));
   return {garment_id:grant.garment_id,name:item && item.name || '共用衣物',reason:grant.reason,sources:(grant.sources||[]).map(sourceView),periods:(grant.periods||[]).map(p=>({...p,nickname:childNames.get(String(p.child_id)) || '宝贝',label:periodLabel(p)}))};
  });
  const conflicts=(review && review.conflicts || []).map(c=>{
   const item=[...snapshot.main_items,...snapshot.backup.items].find(i=>v.itemId(i)===String(c.garment_id));
   return {...c,garment:item || {name:'共用衣物'},usageLabel:(c.usage||[]).map(u=>u==='backup'?'备用':'主搭配').join(' · '),sources:(c.sources||[]).map(sourceView)};
  });
  this.setData({reviewIdentity:labels,reviewSnapshot:snapshot,...(this.data.completedPlan?{completedView:snapshot}:{}),packingItems:packing(snapshot),reservationChanges:reservationChanges(d),sharingSummary,weatherUnknown:!weather || weather.status!=='known',review:review?{...review,conflicts}:null,error:caregiverCopy(this.data.error)});
  if(this.data.sharingOpen && this._sharingScope!==sharingScope(this,conflicts.find(c=>String(c.garment_id)===this.data.sharingId)))this.invalidateSharing();
 },
 preflight(){
  if(!v.writable(this)||this.data.unknownResult||this.data.notSaved)return;
  const current=v.ticket(this),ack=this.data.weatherAcknowledged,draft=getRuntime().outfitStore.get(),ackBasis=draft.weather_acknowledgement_key || weatherKey(draft.weather || this.data.weather);
  return this.run(async valid=>{
   const result=await getRuntime().outfits.review(this.familyId,v.payload(this));if(!valid() || !current() || ack!==this.data.weatherAcknowledged)return;
   if(result.weather){
    this.setData({weather:result.weather});
    if(ack && ackBasis!==weatherKey(result.weather)){
     getRuntime().outfitStore.patch({weather:result.weather,weather_acknowledged:false,weather_acknowledgement_key:null});v.sync(this);this.setData({review:null,error:'目标日天气依据有变化，请重新核对衣物适宜性。'});this.refreshDisplay();await this.displayImages('reviewSnapshot');return;
    }
   }
   this.setData({review:{...result,warnings:v.messages((result.warnings||[]).filter(x=>x.code!=='WEATHER_UNKNOWN')).map(caregiverCopy),missing:v.messages(result.missing).map(caregiverCopy)}});this.refreshDisplay();await this.displayImages('reviewSnapshot');
  });
 },
 weatherAck(){if(!v.writable(this)||this.data.unknownResult||this.data.notSaved)return;const acknowledged=!this.data.weatherAcknowledged;getRuntime().outfitStore.patch({weather_acknowledged:acknowledged,weather_acknowledgement_key:acknowledged?weatherKey(this.data.weather):null});v.sync(this);this.refreshDisplay();return this.preflight();},
 save(){
  if(this.data.unknownResult)return this.query();if(!v.writable(this)||this.data.busy||this.data.completedPlan)return;
  if(this.data.notSaved){this.setData({error:'这次未保存。请重新核对草稿后再选定。'});return;}
  if(this.data.garmentReviewOpen){this.setData({error:'请先确认最新衣物资料，或保留原草稿。'});return;}
  if(this.data.sharingDirty || this.data.sharingOpen){this.setData({error:'分时安排有未确认的填写，请确认或取消后保存。'});return;}
  if(this.data.draft && this.data.draft.backup_staging){this.setData({error:'备用还有未确认的暂存选择，请先确认或取消备用。'});return;}
  if(this.data.draft && this.data.draft.backup_needs_review){this.setData({error:'主搭配有调整，请重新核对备用或明确移除。'});return;}
  const weather=this.data.review && this.data.review.weather || this.data.weather;
  if((!weather || weather.status!=='known') && !this.data.weatherAcknowledged){this.setData({error:'未获取目标日天气，请先由家长核对衣物适宜性并确认继续。'});return;}
  if(!this.data.review || !this.data.review.valid){this.setData({error:'请先处理衣物、天气与共用提示，再保存。'});return;}return this.performSave();
 },
 performSave(){
  const current=v.ticket(this,{draft:false}),family=this.familyId,submission={...v.payload(this),input_version:this.data.review.input_version};
  this._submittedDraftId=submission.draft_id;
  return this.run(async valid=>{const applicable=()=>valid() && current(),result=await getRuntime().outfits.save(family,submission);if(applicable()){await this.finish(result);if(result.plan && applicable())await this.currentNotes(result.plan,applicable);}},true).then(()=>{
   if(current()){const pending=getRuntime().outfits.pending(family,submission.target_date,submission.child_id);if(pending){this._pendingSnapshot=richOriginal(getRuntime(),family,pending.payload);this.setData({unknownResult:true,review:null});}this.refreshDisplay();}
  });
 },
 async finish(result){
  if(result.status!=='completed'){this.setData({unknownResult:true,error:'正在确认保存结果，请继续查看这次保存。'});this.refreshDisplay();return;}
  if(result.plan){getRuntime().outfitStore.completeSelection(result.plan,this._submittedDraftId || this.data.draft && this.data.draft.draft_id,this.familyId);this.setData({completedPlan:copy(result.plan),unknownResult:false,notSaved:false,error:'',sharingOpen:false,sharingDirty:false,latestView:null});this.refreshDisplay();await this.displayImages('completedView');}
  else {this.setData({unknownResult:false,notSaved:true,error:caregiverCopy(result.error && result.error.message) || '这次保存未执行，草稿已保留。重新核对后可以再次选定。',review:null});this.refreshDisplay();}
 },
 resumeReview(){if(!v.writable(this))return;this.setData({notSaved:false,review:null});this._pendingSnapshot=null;return this.reload();},
 query(){if(!['admin','editor','viewer'].includes(getRuntime().session.capability(this.familyId).role))return;const family=this.familyId,date=this.data.targetDate,child=operationChild(this),current=v.ticket(this,{draft:false}),original=getRuntime().outfits.pending(family,date,child);if(original)this._submittedDraftId=original.payload.draft_id;return this.run(async valid=>{const applicable=()=>valid() && current(),result=await getRuntime().outfits.queryOperation(family,date,child);if(applicable()){await this.finish(result);if(result.plan && applicable())await this.currentNotes(result.plan,applicable);}}).then(()=>{if(current())this.refreshDisplay();});},
 async currentNotes(plan,valid){
  const latest=await getRuntime().outfits.context(this.familyId,{child_id:plan.child_id,target_date:plan.target_date,scene:plan.scene,preference_mode:plan.preference_subject && plan.preference_subject.mode,designated_member_id:plan.preference_subject && plan.preference_subject.membership_id});
  if(!valid())return;const now=(latest.plans||[]).find(p=>p.id===plan.id);this._outfitContext=latest;
  this.setData({currentNotes:[...v.messages(now && now.current_warnings || []).map(caregiverCopy),...(now && now.version>plan.version?['家人后来又修改了这套。这里保留你当时选定的内容，当前已选安排如下。']:[])],latestView:now && now.version>plan.version?snapshotView(now):null});this.refreshDisplay();if(this.data.latestView)await this.displayImages('latestView');
 },
 async resolve(){
  if(!this.data.ready || !this.data.writable || !getRuntime().session.canEdit(this.familyId))return;
  if(!await confirmation('核实这次保存','先核实这次是否已保存。只有明确未保存，才可以重新核对后再选定；核实期间保留原提交内容。'))return;
  const family=this.familyId,date=this.data.targetDate,child=operationChild(this),current=v.ticket(this,{draft:false});
  return this.run(async valid=>{const applicable=()=>valid() && current(),result=await getRuntime().outfits.resolveOperation(family,date,child);if(applicable()){await this.finish(result);if(result.plan && applicable())await this.currentNotes(result.plan,applicable);}},true).then(()=>{if(current())this.refreshDisplay();});
 },
 openSharing(e){
  if(!v.writable(this)||this.data.unknownResult)return;this._sharingRequest=(this._sharingRequest||0)+1;
  const id=String(e.currentTarget.dataset.id),conflict=(this.data.review && this.data.review.conflicts||[]).find(c=>String(c.garment_id)===id);if(!conflict)return;
  const children=new Map([[String(this.data.draft.child_id),{child_id:String(this.data.draft.child_id),nickname:identity(this,this.data.draft).childNickname}]]);
  for(const s of conflict.sources)children.set(String(s.child_id),{child_id:String(s.child_id),nickname:s.nickname || '另一位宝贝'});
  const confirmed=conflict.resolved && (this.data.draft.sharing_grants||[]).find(g=>String(g.garment_id)===id),snapshot=this.data.reviewSnapshot || this.data.draft;
  const garment=[...snapshot.main_items,...snapshot.backup.items].find(i=>v.itemId(i)===id);
  this._sharingScope=sharingScope(this,conflict);
  this.setData({sharingOpen:true,sharingDirty:false,sharingId:id,sharingGarment:garment,sharingSources:conflict.sources,sharingReason:confirmed?confirmed.reason:'',periods:[...children.values()].map(x=>formPeriod({...x,...(confirmed && confirmed.periods.find(p=>String(p.child_id)===x.child_id)||{start:'',end:''})}))});this.validateSharing();
 },
 choosePeriod(e){if(!v.writable(this)||!this.data.sharingOpen)return;const preset=periodOptions[Number(e.detail.value)];if(!preset)return;this.setData({sharingDirty:true,periods:this.data.periods.map(p=>p.child_id===String(e.currentTarget.dataset.id)?formPeriod({...p,start:preset.start,end:preset.end}):p)});this.validateSharing();},
 period(e){if(!v.writable(this))return;const {id,field}=e.currentTarget.dataset;this.setData({sharingDirty:true,periods:this.data.periods.map(p=>p.child_id===String(id)?formPeriod({...p,[field]:e.detail.value}):p)});this.validateSharing();},
 sharingReason(e){if(v.writable(this)){this.setData({sharingDirty:true,sharingReason:e.detail.value});this.validateSharing();}},
 validateSharing(){
  const periods=this.data.periods,reason=this.data.sharingReason.trim(),ordered=periods.slice().sort((a,b)=>a.start.localeCompare(b.start));
  const message=!periods.length || periods.some(p=>!p.start || !p.end || p.start>=p.end)?'请为每位宝贝选择时段。':ordered.some((p,i)=>i && ordered[i-1].end>p.start)?'时段有重叠，请为宝贝选择不同的时段。':!reason?'请说明为什么能这样分时安排。':'';
  this.setData({sharingReady:!message,sharingValidation:message});return !message;
 },
 cancelSharing(){this._sharingRequest=(this._sharingRequest||0)+1;this._sharingScope=null;this.setData({sharingOpen:false,sharingDirty:false,sharingReady:false,sharingValidation:'',periods:[],sharingReason:'',sharingSources:[],sharingGarment:null,sharingId:''});},
 invalidateSharing(){this.cancelSharing();this.setData({error:'共用的已选来源或草稿有变化，请重新核对全部来源再安排分时。'});},
 confirmSharing(){
  if(!v.writable(this)||!this.data.sharingOpen||this.data.unknownResult)return;
  const conflict=(this.data.review && this.data.review.conflicts||[]).find(c=>String(c.garment_id)===this.data.sharingId);
  if(this._sharingScope!==sharingScope(this,conflict)){this.invalidateSharing();return;}
  if(!this.validateSharing()){this.setData({error:this.data.sharingValidation});return;}
  const current=v.ticket(this),request=this._sharingRequest,scope=this._sharingScope,form=JSON.stringify([this.data.sharingId,this.data.sharingReason,this.data.periods]);
  return this.run(async valid=>{
   const rt=getRuntime(),result=await rt.outfits.sharing(this.familyId,{...v.payload(this),garment_id:this.data.sharingId,reason:this.data.sharingReason.trim(),periods:this.data.periods.map(({child_id,start,end})=>({child_id,start,end}))});
   if(valid() && current() && request===this._sharingRequest && this.data.sharingOpen && scope===this._sharingScope && form===JSON.stringify([this.data.sharingId,this.data.sharingReason,this.data.periods])){
    const d=rt.outfitStore.get(),grant=result.grant || result;
    if(sourceBinding(grant)!==sourceBinding(conflict) || String(grant.family_id)!==String(this.familyId) || String(grant.child_id)!==String(d.child_id) || grant.target_date!==d.target_date || grant.draft_id!==d.draft_id || String(grant.target_plan_id || '')!==String(d.target_plan_id || '')){this.invalidateSharing();this.setData({review:null});return;}
    rt.outfitStore.patch({sharing_grants:[...(d.sharing_grants||[]).filter(g=>String(g.garment_id)!==this.data.sharingId),grant]});v.sync(this);this.cancelSharing();this.refreshDisplay();await this.preflight();
   }
  },true);
 },
 compare(){return this.run(async valid=>{const context=await getRuntime().outfits.context(this.familyId,{child_id:this.data.draft.child_id,target_date:this.data.targetDate});if(!valid())return;const latest=(context.plans || []).find(p=>p.id===this.data.draft.target_plan_id);this.setData({latestPlan:latest || null,latestView:latest?snapshotView(latest):null,compareOpen:true});if(latest)await this.displayImages('latestView');});},
 closeCompare(){this.setData({compareOpen:false});},
 async useLatest(){if(!v.writable(this)||!this.data.latestPlan||this.data.unknownResult)return;if(!await confirmation('重新编辑最新方案','放弃当前未保存调整，从家人最新方案重新开始？'))return;getRuntime().outfitStore.beginEdit(this.data.latestPlan,false);v.sync(this);this.setData({compareOpen:false,review:null});this.refreshDisplay();return this.preflight();},
 async asNew(){if(!v.writable(this)||this.data.unknownResult)return;if(!await confirmation('明确新增一套','保留原方案，将当前草稿作为新方案。共用安排需要重新核对。'))return;const rt=getRuntime(),d=rt.outfitStore.get();rt.outfitStore.beginEdit({...d,id:d.target_plan_id,version:d.expected_version},true);v.sync(this);this.setData({compareOpen:false,review:null});this.refreshDisplay();return this.preflight();},
 latestGarments(){
  if(!v.writable(this)||this.data.unknownResult||this.data.completedPlan)return;
  const rt=getRuntime(),current=v.ticket(this),draft=rt.outfitStore.get(),request=this._garmentRequest=(this._garmentRequest||0)+1;
  return this.run(async valid=>{
   const context=await rt.outfits.context(this.familyId,{child_id:draft.child_id,target_date:draft.target_date,scene:draft.scene,preference_mode:draft.preference_mode,designated_member_id:draft.designated_member_id,...v.location(),...(this._location||{})});
   if(!valid()||!current()||request!==this._garmentRequest)return;
   const latest=new Map((context.garments||[]).map(i=>[v.itemId(i),i]));
   const row=(item,usage)=>{const next=latest.get(v.itemId(item));return {id:usage+':'+v.itemId(item),usage,name:item.name || '衣物',previous:item,current:next || null,available:!!(next && next.eligible),message:next?next.eligibility_reason || (next.eligible?'可用于当前宝贝与日期':'当前不可用于这套'):'衣物已移除或不再属于这个家庭'};};
   this._garmentReviewCurrent=current;
   this.setData({garmentReviewOpen:true,latestGarmentRows:[...draft.main_items.map(i=>row(i,'main')),...draft.backup.items.map(i=>row(i,'backup'))]});
  });
 },
 cancelGarments(){this._garmentRequest=(this._garmentRequest||0)+1;this._garmentReviewCurrent=null;this.setData({garmentReviewOpen:false,latestGarmentRows:[]});},
 confirmGarments(){
  if(!v.writable(this)||this.data.unknownResult||this.data.completedPlan||!this.data.garmentReviewOpen)return;
  if(!this._garmentReviewCurrent || !this._garmentReviewCurrent()){this.cancelGarments();this.setData({error:'草稿或当前条件已变化，请重新核对衣物资料。'});return;}
  const rows=this.data.latestGarmentRows;
  if(rows.some(i=>!i.available)){this.setData({error:'有衣物当前不可使用。请先替换主搭配或明确移除备用，再核对最新资料。'});return;}
  const rt=getRuntime(),draft=rt.outfitStore.get();
  const update=(item,usage)=>{const row=rows.find(r=>r.usage===usage && v.itemId(r.previous)===v.itemId(item));return {...row.current,expected_version:row.current.version,...(item.replaces_garment_id?{replaces_garment_id:item.replaces_garment_id}:{})};};
  rt.outfitStore.patch({main_items:draft.main_items.map(i=>update(i,'main')),backup:{...draft.backup,items:draft.backup.items.map(i=>update(i,'backup'))},backup_needs_review:!!draft.backup_needs_review});
  this.cancelGarments();v.sync(this);this.setData({review:null});this.refreshDisplay();return this.preflight();
 },
 removeBackup(){if(!v.writable(this)||this.data.unknownResult)return;const rt=getRuntime();rt.outfitStore.stageBackup({mode:'none',items:[]});rt.outfitStore.confirmBackup();v.sync(this);this.refreshDisplay();return this.preflight();},
 edit(){if(v.writable(this) && !this.data.unknownResult)navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate));},
 async displayImages(field){
  const rt=getRuntime(),snapshot=this.data[field];if(!snapshot)return;
  const generation=rt.session.generation(),access=rt.session.capability(this.familyId).epoch,context=rt.context.capture(),load=this._load||0,fingerprint=snapshotKey(snapshot);
  const valid=()=>this._visible!==false && generation===rt.session.generation() && access===rt.session.capability(this.familyId).epoch && ['admin','editor','viewer'].includes(rt.session.capability(this.familyId).role) && rt.context.isCurrent(context) && load===(this._load||0) && this.data[field] && snapshotKey(this.data[field])===fingerprint;
  const assets=[...new Set([...snapshot.main_items,...snapshot.backup.items].map(i=>i.asset_id).filter(Boolean))];
  for(const asset of assets)try{
   const image=await rt.media.image(this.familyId,asset);if(!valid())return;
   const current=this.data[field],apply=list=>list.map(i=>i.asset_id===asset?{...i,image}:i),next={...current,main_items:apply(current.main_items),backup:{...current.backup,items:apply(current.backup.items)}};
   this.setData({[field]:next});if(field==='reviewSnapshot' || field==='completedView'){this.setData({packingItems:packing(next)});this.refreshDisplay();}
  }catch(e){if(this.handleAccessError(e,generation))return;if(valid())this.setData({imageMessage:'部分原图暂时未加载，可点衣物重新查看。'});}
 },
 preview(e){const id=String(e.currentTarget.dataset.id),field=e.currentTarget.dataset.view || (this.data.completedPlan?'completedView':'reviewSnapshot'),snapshot=this.data[field];const item=[...(snapshot && snapshot.main_items || []),...(snapshot && snapshot.backup && snapshot.backup.items || [])].find(i=>v.itemId(i)===id);if(item && item.asset_id)return this.run(()=>getRuntime().media.preview(this.familyId,item.asset_id));},
 back(){if(this.data.sharingOpen){this.cancelSharing();return;}if(this.data.garmentReviewOpen){this.cancelGarments();return;}if(this.data.compareOpen){this.closeCompare();return;}wx.navigateBack();},home(){wx.reLaunch({url:'/pages/home/home'});},wardrobe(){navigate('wardrobe');},my(){navigate('my');},noop(){},
 onEditRevoked(){this._pendingSnapshot=null;this._sharingScope=null;this._garmentReviewCurrent=null;this._sharingRequest=(this._sharingRequest||0)+1;this._garmentRequest=(this._garmentRequest||0)+1;v.accessRevoked(this);this.setData({sharingSources:[],sharingGarment:null,sharingReady:false,sharingValidation:''});if(getRuntime().session.capability(this.familyId).role===null){this._submittedDraftId=null;this.setData({reviewIdentity:null,reviewSnapshot:null,completedView:null,latestView:null,latestPlan:null,packingItems:[],sharingSummary:[],reservationChanges:null,members:[],notSaved:false,periods:[],sharingReason:'',sharingId:''});}}
}));

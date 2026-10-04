const {getRuntime}=require('./runtime');
const {navigate}=require('./page');
const {display,label,fits}=require('./garment-forms');
const {ageLabel}=require('./forms');
const scenes=[{key:'daily',name:'日常'},{key:'outdoor',name:'户外'},{key:'school',name:'上学'},{key:'formal',name:'正式场合'},{key:'sport',name:'运动'}];
function itemId(i){return String(i.garment_id || i.id);}
function items(values=[]){return values.map(i=>({...display({...i,id:itemId(i)}),fitLabel:label(fits,i.fit),garment_id:itemId(i),expected_version:i.expected_version || i.version}));}
function messages(values=[]){return values.map(x=>typeof x==='string'?x:x.message || x.code || '请重新核对');}
function draftView(d,currentGarments){
 if(!d)return null;
 const all=[...(d.main_items||[]),...(d.backup && d.backup.items||[])],photos=new Map();
 for(const i of all)if(i.asset_id){const ids=photos.get(String(i.asset_id))||new Set();ids.add(itemId(i));photos.set(String(i.asset_id),ids);}
 const present=values=>items(values).map(i=>{
  const latest=currentGarments && currentGarments.find(g=>itemId(g)===itemId(i));
  const unavailable=currentGarments && (!latest || latest.eligible===false || latest.state && latest.state!=='ready' || latest.fit==='unknown');
  const changed=latest && latest.version!==undefined && latest.version!==i.expected_version;
  return {...i,photoNote:i.asset_id && photos.get(String(i.asset_id)).size>1?'同一张原图中的不同实物，请查看原图定位':'',
   currentStateLabel:latest?display(latest).stateLabel:'',currentFitLabel:latest?label(fits,latest.fit):'',
   currentIssue:unavailable?(i.name||i.categoryLabel)+'当前'+(latest && latest.state && latest.state!=='ready'?display(latest).stateLabel:latest && latest.eligibility_reason || '可用或合身情况需核对'):
    changed?(i.name||i.categoryLabel)+'资料已变化，请核对当前情况':'',
   fixed:(d.locked_ids||[]).includes(itemId(i))};
 });
 return {...d,main_items:present(d.main_items),lockedLabel:(d.locked_ids||[]).map(id=>all.find(i=>itemId(i)===String(id))).filter(Boolean).map(i=>i.name||display(i).categoryLabel).join('、')||'无',backup:{...(d.backup||{mode:'none'}),items:present(d.backup && d.backup.items)}};
}
function dateLabel(value){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return '';
 const date=new Date(value+'T12:00:00Z');if(Number.isNaN(date.getTime()))return '';
 return Number(value.slice(5,7))+'月'+Number(value.slice(8,10))+'日 周'+['日','一','二','三','四','五','六'][date.getUTCDay()];
}
function nextDate(value){if(!dateLabel(value))return '';const date=new Date(value+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+1);return date.toISOString().slice(0,10);}
function contextLabels(page,basis={}){
 const rt=getRuntime(),context=page._outfitContext||{},cid=basis.child_id || context.child && context.child.id || page.data.child && page.data.child.id;
 const children=[context.child,page.data.child,...(page.data.children||[]),...(rt.session.read(page.familyId,'children')||[])].filter(Boolean);
 const child=children.find(c=>String(c.id)===String(cid));
 const subject=basis.preference_subject || context.preference_subject || {},mode=basis.preference_mode || subject.mode || 'family',memberId=basis.designated_member_id || subject.membership_id;
 const member=(page.data.members||[]).find(m=>String(m.id)===String(memberId) && (!m.status || m.status==='active'));
 const name=member && member.nickname || (mode==='current_member' && !memberId && rt.session.user() && rt.session.user().nickname);
 const today=context.today || page.data.today,reference=today && new Date(Number(today.slice(0,4)),Number(today.slice(5,7))-1,Number(today.slice(8,10)));
 const target=basis.target_date || context.target_date || page.data.targetDate;
 return {childNickname:child && child.nickname || '当前宝贝',childInitial:(child && child.nickname || '宝').slice(0,1),childAge:child?ageLabel(child,reference || new Date()):'',
  targetDateLabel:dateLabel(target),dateLabel:dateLabel(target),sceneLabel:(scenes.find(s=>s.key===(basis.scene || context.scene))||scenes[0]).name,
  preferenceLabel:mode==='family'?'家庭统一偏好':name?name+'的偏好':mode==='current_member'?(memberId?'选择时使用者偏好需核对':'当前使用者偏好'):'原指定成员偏好需核对'};
}
function currentItems(page,d){const c=page._outfitContext;return c && (!c.child || !d.child_id || String(c.child.id)===String(d.child_id))?c.garments:undefined;}
function currentWarnings(page){const d=page.data.draft;return d?[...(d.main_items||[]),...(d.backup && d.backup.items||[])].map(i=>i.currentIssue).filter(Boolean):[];}
function errorState(e){return {error:e.message || '操作失败，请重试',conflict:e.status===409 && e.code==='VERSION_CONFLICT'};}
const presentationReset={latestPlan:null,periods:[],sharingReason:'',sharingId:'',reservationChanges:null,sharingGarment:null,sharingReady:false,sharingValidation:'',notSaved:false,members:[],childNickname:'',childAge:'',childInitial:'',targetDateLabel:'',dateLabel:'',todayLabel:'',tomorrowLabel:'',sceneLabel:'',preferenceLabel:'',reviewIdentity:null,reviewSnapshot:null,packingItems:[],sharingSummary:[],sharingSources:[],completedView:null,latestView:null,planViews:[],operationOpen:false,operationItem:null};
function location(){const {session}=getRuntime(),v=session.read('_','location');return v && v.mode==='manual'?{city:v.city}:{};}
function bindPage(page){
 const rt=getRuntime(),family=rt.session.read('_','family'),owner={user:rt.session.user() && rt.session.user().id,generation:rt.session.generation(),family,child:family && rt.session.read(family,'child')};
 if(!page._owner || Object.keys(owner).some(k=>page._owner[k]!==owner[k])){
  page._load=(page._load||0)+1;page._contextRequest=(page._contextRequest||0)+1;
  page._outfitContext=null;
  page.setData({...presentationReset,ready:false,busy:false,loading:false,error:'',conflict:false,draft:null,completedPlan:null,currentNotes:[],weather:null,review:null,plans:[],candidates:[],stagedCandidate:null,candidateOpen:false,backupOpen:false,backupChoices:[],stagedBackup:null,sharingOpen:false,sharingDirty:false,periods:[],sharingReason:'',latestPlan:null,compareOpen:false,garmentReviewOpen:false,latestGarmentRows:[],unknownResult:false,draftFrozen:false,sourceOrigin:false,writable:false});
 }
 page._owner=owner;page.familyId=family;
 if(!rt.session.token()){wx.reLaunch({url:'/pages/login/login'});return false;}
 if(!family){navigate('families');return false;}return true;
}
function writable(page){return !!(!page.data.completedPlan && !page.data.draftFrozen && !(page.data.draft && page.data.draft.status==='completed') && page.data.ready && page.data.writable && getRuntime().session.canEdit(page.familyId));}
function sync(page){const rt=getRuntime(),d=rt.outfitStore.get();if(!d)return;const pending=rt.outfits.pending(page.familyId,d.target_date,d.child_id);page.setData({draft:draftView(d,currentItems(page,d)),dirty:!!d.dirty,sourceOrigin:!!d.source_origin,unknownResult:!!pending,draftFrozen:!!(pending && pending.payload && pending.payload.draft_id===d.draft_id),weatherAcknowledged:!!d.weather_acknowledged});}
function payload(page){const rt=getRuntime(),d=rt.outfitStore.payload();return {...d,...location(),...(page._location || {}),weather_acknowledged:!!d.weather_acknowledged};}
async function images(page){const rt=getRuntime(),generation=rt.session.generation(),epoch=rt.session.capability(page.familyId).epoch,ticket=rt.context.capture(),load=page._load || 0;const valid=()=>page._visible!==false && load===(page._load || 0) && generation===rt.session.generation() && epoch===rt.session.capability(page.familyId).epoch && rt.context.isCurrent(ticket);const d=page.data.draft;if(!d)return;const all=[...(d.main_items || []),...(d.backup && d.backup.items || [])];for(const i of all){if(!i.asset_id)continue;try{const path=await rt.media.image(page.familyId,i.asset_id);if(!valid())return;const current=page.data.draft;if(!current || current.draft_id!==d.draft_id || current.revision!==d.revision)return;const apply=list=>list.map(x=>itemId(x)===itemId(i)?{...x,image:path}:x);page.setData({draft:{...current,main_items:apply(current.main_items),backup:{...current.backup,items:apply(current.backup.items)}}});}catch(e){if(page.handleAccessError(e,generation))return;if(valid())page.setData({imageMessage:'部分原图暂不可用，可点衣物重新查看。'});}}}
async function preview(page,e){const id=e.currentTarget.dataset.id,d=page.data.draft;const i=[...(d && d.main_items || []),...(d && d.backup && d.backup.items || [])].find(x=>itemId(x)===String(id));if(i && i.asset_id)return page.run(()=>getRuntime().media.preview(page.familyId,i.asset_id));}
function ticket(page,{draft=true}={}){const rt=getRuntime(),generation=rt.session.generation(),access=rt.session.capability(page.familyId).epoch,context=rt.context.capture(),load=page._load||0,d=rt.outfitStore.get();return ()=>page._visible!==false && load===(page._load||0) && generation===rt.session.generation() && access===rt.session.capability(page.familyId).epoch && rt.context.isCurrent(context) && (!draft || !d || (()=>{const n=rt.outfitStore.get();return n && n.draft_id===d.draft_id && n.revision===d.revision;})());}
async function refreshContext(page,{open=true,dateMode,basisOverride,valid=()=>true}={}){
 const rt=getRuntime(),fid=page.familyId,cid=rt.session.read(fid,'child');if(!cid)return null;
 const epoch=page._contextRequest=(page._contextRequest||0)+1,load=page._load||0,daily=page._outfitEpoch,initialDate=page.data.targetDate,initialMode=page.data.mode,generation=rt.session.generation(),ctx=rt.context.capture();
 const current=()=>valid() && page._visible!==false && epoch===page._contextRequest && load===(page._load||0) && daily===page._outfitEpoch && initialDate===page.data.targetDate && initialMode===page.data.mode && generation===rt.session.generation() && rt.context.isCurrent(ctx);
 const assertCurrent=()=>{if(!current())throw Object.assign(new Error('已切换当前搭配'),{code:'STALE'});};
 const currentDraft=rt.outfitStore.get();
 let basis=basisOverride || (currentDraft && String(currentDraft.child_id)===String(cid) && currentDraft.target_date===initialDate?{scene:currentDraft.scene,preference_mode:currentDraft.preference_mode,designated_member_id:currentDraft.designated_member_id}:rt.session.read(fid,'outfit-basis:'+cid)) || {scene:'daily',preference_mode:'family'};
 const query={child_id:cid,...basis,...location(),...(page._location || {})};
 if(initialDate)query.target_date=initialDate;else query.date_mode=dateMode || rt.outfitStore.dateMode(fid,cid) || 'today';
 let result=await rt.outfits.context(fid,query);assertCurrent();rt.session.capability(fid,result.role);
 if(open && rt.session.canEdit(fid)){
  let restored=rt.outfitStore.open(fid,cid,result.target_date,{...basis,preference_subject:result.preference_subject});
  if(basisOverride && restored.status==='completed'){
   const selected=(result.plans||[]).find(p=>p.id===restored.completed_plan_id);
   if(!selected)throw new Error('这份草稿已经选定，请从首页明确修改或新增一套。');
   restored=rt.outfitStore.beginEdit(selected,true);
  }
  if(basisOverride && restored.scene!==basisOverride.scene)restored=rt.outfitStore.patch({scene:basisOverride.scene});
  const restoredBasis={scene:restored.scene,preference_mode:restored.preference_mode,designated_member_id:restored.designated_member_id};
  if(JSON.stringify([basis.scene,basis.preference_mode,basis.designated_member_id || null])!==JSON.stringify([restoredBasis.scene,restoredBasis.preference_mode,restoredBasis.designated_member_id || null])){
   result=await rt.outfits.context(fid,{child_id:cid,target_date:result.target_date,...restoredBasis,...location(),...(page._location||{})});assertCurrent();rt.session.capability(fid,result.role);
  }
  basis=restoredBasis;sync(page);
 }
 page._outfitContext=result;
 page.setData({...contextLabels(page,{...basis,target_date:result.target_date,preference_subject:result.preference_subject}),todayLabel:dateLabel(result.today),tomorrowLabel:dateLabel(nextDate(result.today)),targetDate:result.target_date,today:result.today,timezone:result.timezone,weather:result.weather,role:result.role,writable:rt.session.canEdit(fid),contextReady:true,plans:result.plans || [],inputVersion:result.input_version});
 if(open && rt.session.canEdit(fid))sync(page);
 return result;
}
function toReview(page){if(!writable(page))return;navigate('outfit-review','?date='+encodeURIComponent(page.data.targetDate));}
function accessRevoked(page){const rt=getRuntime();if(rt.outfitStore.refresh)rt.outfitStore.refresh();page._outfitContext=null;page.setData({writable:false,candidateOpen:false,candidates:[],stagedCandidate:null,sharingOpen:false,sharingDirty:false,backupOpen:false,garmentReviewOpen:false,latestGarmentRows:[],operationOpen:false,operationItem:null,sharingSources:[],sharingSummary:[]});if(rt.session.capability(page.familyId).role===null){page._pendingSnapshot=null;page._submittedDraftId=null;page.setData({...presentationReset,draft:null,plans:[],weather:null,review:null,completedPlan:null,currentNotes:[],ready:false,busy:false,loading:false,contextReady:false,unknownResult:false,draftFrozen:false,weatherAcknowledged:false});}}
module.exports={bindPage,messages,scenes,itemId,items,draftView,contextLabels,dateLabel,nextDate,currentWarnings,errorState,location,writable,sync,payload,images,preview,refreshContext,toReview,accessRevoked,ticket};

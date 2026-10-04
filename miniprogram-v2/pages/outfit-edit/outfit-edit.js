const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,confirmation,membership}=require('../../services/page');
const {fits,label}=require('../../services/garment-forms');
const v=require('../../services/outfit-view');

Page(definePage({
 errorState:v.errorState,
 data:{
  draft:null,writable:false,targetDate:'',members:[],operationOpen:false,operationItem:null,operationUsage:'main',
  lockedItems:[],excludedItems:[],emptySlots:[],backupLabel:'无备用',packingCount:0,backupPackingCount:0,
  candidates:[],replaceId:'',replaceItem:null,stagedCandidate:null,candidateOpen:false,
  backupOpen:false,backupMode:'none',stagedBackup:null,backupChoices:[],
  unknownResult:false,draftFrozen:false,sourceOrigin:false,reason:'',imageMessage:''
 },
 onLoad(o){this.data.targetDate=o.date || '';this.origin=o.origin==='1';this.requestedItem=o.item;this.requestedUsage=o.usage || 'main';},
 onShow(){
  this._visible=true;this._knownItems=new Map();this._vacantItems=[];this.closeItem();
  this.setData({members:[],lockedItems:[],excludedItems:[],emptySlots:[],backupLabel:'无备用',packingCount:0,reason:'',imageMessage:''});
  if(!v.bindPage(this))return;this.reload();
 },
 reload(){return this.run(async valid=>{
  const rt=getRuntime(),info=await membership(this.familyId);if(!valid())return;
  rt.session.capability(this.familyId,info.role);
  this.setData({ready:true,writable:rt.session.canEdit(this.familyId),role:info.role,members:info.members.filter(m=>m.status==='active')});
  if(!this.data.writable){this.setData({error:'当前仅可查看已选搭配，请回首页查看。'});return;}
  await v.refreshContext(this,{valid});if(!valid())return;this.decorate();
  if(this.origin){
   const origin=rt.session.read(this.familyId,'outfit-origin');
   if(origin){
    const g=await rt.wardrobe.get(this.familyId,origin.garment_id);if(!valid())return;
    rt.outfitStore.fromGarment(g);rt.session.remove(this.familyId,'outfit-origin');this.origin=false;
    this.syncDraft();this.setData({sourceOrigin:true});await this.generate();
   }
  }
  this.syncDraft();
  if(this.data.draft && this.data.draft.status==='completed')this.setData({writable:false,error:'这份草稿已经选定，请从首页明确修改或新增一套。'});
  if(this.requestedItem){
   const id=this.requestedItem,usage=this.requestedUsage;this.requestedItem=null;
   if(v.writable(this))this.openItem({currentTarget:{dataset:{id,usage}}});
  }
  this.loadDraftImages();
 });},
 onHide(){
  this._visible=false;this._load=(this._load||0)+1;
  this._candidateRequest=(this._candidateRequest||0)+1;this._backupRequest=(this._backupRequest||0)+1;
  this.closeItem();this.setData({candidateOpen:false,backupOpen:false,candidates:[],stagedCandidate:null,stagedBackup:null,backupChoices:[],replaceItem:null});
  getRuntime().outfitStore.invalidate();
 },
 onUnload(){this.onHide();},
 remember(items=[]){
  if(!this._knownItems)this._knownItems=new Map();
  for(const i of items)if(i && (i.id || i.garment_id))this._knownItems.set(v.itemId(i),i);
 },
 decorate(){
  const d=this.data.draft;if(!d)return;
  if(this._vacantDraftId!==d.draft_id){this._vacantItems=[];this._vacantDraftId=d.draft_id;}
  const context=this._outfitContext || {},all=[...(context.garments || []),...(d.main_items || []),...(d.backup && d.backup.items || [])];
  this.remember(all);
  const present=i=>({...i,fitLabel:i.fitLabel || label(fits,i.fit)});
  const main=(d.main_items || []).map(present),backup={...(d.backup || {mode:'none'}),items:(d.backup && d.backup.items || []).map(present)};
  const named=id=>{const i=this._knownItems.get(String(id)) || {};return {id,name:i.name || '已排除的衣物',category:i.category,categoryLabel:i.categoryLabel || '单品'};};
  const excludedItems=(d.excluded_ids || []).map(named),slotCategories=new Set();
  const emptySlots=(this._vacantItems || []).filter(i=>i.category && !main.some(m=>m.category===i.category) && !slotCategories.has(i.category) && slotCategories.add(i.category));
  const operation=(this.data.operationUsage==='backup'?backup.items:main).find(i=>v.itemId(i)===v.itemId(this.data.operationItem || {}));
  this.setData({
   ...v.contextLabels(this,d),
   draft:{...d,main_items:main,backup},lockedItems:main.filter(i=>i.fixed),excludedItems,emptySlots,
   backupLabel:backup.mode==='none'?'无备用':(backup.mode==='full'?'整套备用':'局部备用')+' · '+backup.items.length+'件',
   packingCount:new Set([...main,...backup.items].map(v.itemId)).size,
   ...(this.data.operationOpen?{operationItem:operation || null,operationOpen:!!operation}:{})
  });
 },
 syncDraft(){this.remember([...(this.data.draft && this.data.draft.main_items || []),...(this.data.draft && this.data.draft.backup && this.data.draft.backup.items || [])]);v.sync(this);this.decorate();},
 loadDraftImages(){const current=v.ticket(this);return v.images(this).then(()=>{if(current())this.decorate();});},
 openItem(e){
  if(!this.data.ready || !getRuntime().session.capability(this.familyId).role || !this.data.draft)return;
  const usage=e.currentTarget.dataset.usage || 'main',list=usage==='backup'?this.data.draft.backup.items:this.data.draft.main_items;
  const item=list.find(i=>v.itemId(i)===String(e.currentTarget.dataset.id));
  if(item)this.setData({operationOpen:true,operationItem:item,operationUsage:usage});
 },
 closeItem(){this.setData({operationOpen:false,operationItem:null});},
 previewOperation(){const i=this.data.operationItem;if(i && i.asset_id)return this.run(()=>getRuntime().media.preview(this.familyId,i.asset_id));},
 replaceOperation(){const i=this.data.operationItem;if(!i)return;const usage=this.data.operationUsage;this.closeItem();return this.replace({currentTarget:{dataset:{id:v.itemId(i),usage}}});},
 fixOperation(){const i=this.data.operationItem;if(i && this.data.operationUsage==='main')this.fix({currentTarget:{dataset:{id:v.itemId(i)}}});},
 excludeOperation(){const i=this.data.operationItem;if(!i || this.data.operationUsage!=='main')return;this.exclude({currentTarget:{dataset:{id:v.itemId(i)}}});if(!(this.data.draft.locked_ids || []).includes(v.itemId(i)))this.closeItem();},
 async hydrateChoices(key,requestKey){
  const rt=getRuntime(),current=v.ticket(this),request=this[requestKey],generation=rt.session.generation(),original=this.data[key];
  const valid=()=>current() && request===this[requestKey] && (key==='candidates'?this.data.candidateOpen:this.data.backupOpen);
  for(const i of original){
   if(!i.asset_id || i.image)continue;
   try{
    const image=await rt.media.image(this.familyId,i.asset_id);if(!valid())return;
    this.setData({[key]:this.data[key].map(x=>v.itemId(x)===v.itemId(i)?{...x,image}:x)});
   }catch(e){if(this.handleAccessError(e,generation))return;if(valid())this.setData({imageMessage:'部分原图暂不可用，仍可查看衣物资料。'});}
  }
 },
 choiceItems(items=[]){
  this.remember(items);
  const photos=new Map();
  for(const i of this._knownItems.values())if(i.asset_id){const ids=photos.get(String(i.asset_id)) || new Set();ids.add(v.itemId(i));photos.set(String(i.asset_id),ids);}
  return v.items(items).map(i=>({...i,fitLabel:i.fitLabel || label(fits,i.fit),
   choiceKey:v.itemId(i)+(i.replaces_garment_id?':'+String(i.replaces_garment_id):''),
   photoNote:i.asset_id && photos.get(String(i.asset_id)).size>1?'同一张原图中的不同实物，请查看原图定位':'',
   backupUseLabel:i.replaces_garment_id?'替换'+((this._knownItems.get(String(i.replaces_garment_id)) || {}).name || '主搭配中的对应单品'):
    (this.data.draft.main_items || []).some(m=>v.itemId(m)===v.itemId(i))?'沿用主搭配中的同一件实物':'整套备用组成'
  }));
 },
 chooseCandidate(e){
  if(!v.writable(this))return;
  const i=this.data.candidates.find(x=>v.itemId(x)===String(e.currentTarget.dataset.id));
  if(i){this._candidateRequest=(this._candidateRequest||0)+1;this.setData({stagedCandidate:i});this.hydrateChoices('candidates','_candidateRequest');}
 },
 cancelCandidates(){
  this._candidateRequest=(this._candidateRequest||0)+1;
  if(v.writable(this) && !this.data.draftFrozen)getRuntime().outfitStore.cancelReplacement();
  this.setData({candidateOpen:false,candidates:[],stagedCandidate:null,replaceItem:null});
 },
 confirmCandidate(){
  if(!v.writable(this)||!this.data.stagedCandidate || this.data.busy)return;
  const rt=getRuntime(),selected=this.data.stagedCandidate,request=this._candidateRequest,current=v.ticket(this),replaceId=this.data.replaceId,usage=this.data.replaceUsage || 'main';
  return this.run(async valid=>{
   const result=await rt.outfits.candidates(this.familyId,{...v.payload(this),replace_id:replaceId,usage});
   if(!valid() || !current() || request!==this._candidateRequest || !this.data.candidateOpen)return;
   const latest=(result.items||[]).find(i=>v.itemId(i)===v.itemId(selected) && (i.expected_version || i.version)===(selected.expected_version || selected.version));
   if(!latest){this.setData({stagedCandidate:null,candidates:this.choiceItems(result.items),error:'候选情况已变化，请重新核对；原搭配保持。'});this.hydrateChoices('candidates','_candidateRequest');return;}
   rt.outfitStore.stageReplacement(replaceId,latest,usage);rt.outfitStore.confirmReplacement();this.syncDraft();this.setData({reason:''});this.cancelCandidates();this.loadDraftImages();
  },true);
 },
 replace(e){
  if(!v.writable(this))return;
  const id=String(e.currentTarget.dataset.id),usage=e.currentTarget.dataset.usage || 'main',d=this.data.draft;
  if(usage==='main' && (d.locked_ids||[]).includes(id)){this.setData({error:'这件已固定，请先明确解除固定再替换。'});return;}
  const current=v.ticket(this),request=this._candidateRequest=(this._candidateRequest||0)+1;
  const item=(usage==='backup'?d.backup.items:d.main_items).find(i=>v.itemId(i)===id);
  return this.run(async valid=>{
   const result=await getRuntime().outfits.candidates(this.familyId,{...v.payload(this),replace_id:id,usage});
   if(valid() && current() && request===this._candidateRequest){
    this.setData({replaceId:id,replaceUsage:usage,replaceItem:item,candidates:this.choiceItems(result.items),candidateOpen:true,stagedCandidate:null,error:result.items.length?'':'没有可替换的合适衣物，当前搭配已保留。'});
    this.hydrateChoices('candidates','_candidateRequest');
   }
  });
 },
 previewCandidate(e){const i=this.data.candidates.find(x=>v.itemId(x)===String(e.currentTarget.dataset.id));if(i && i.asset_id)return this.run(()=>getRuntime().media.preview(this.familyId,i.asset_id),false,{background:true});},
 fix(e){if(!v.writable(this))return;const id=String(e.currentTarget.dataset.id),rt=getRuntime(),locked=this.data.draft.locked_ids || [];rt.outfitStore.fixed(id,!locked.includes(id));this.syncDraft();this.setData({error:''});},
 exclude(e){
  if(!v.writable(this))return;const id=String(e.currentTarget.dataset.id);
  if((this.data.draft.locked_ids||[]).includes(id)){this.setData({error:'请先解除固定，再选择本次不穿。'});return;}
  const item=this.data.draft.main_items.find(i=>v.itemId(i)===id);
  if(item){
   if(this._vacantDraftId!==this.data.draft.draft_id)this._vacantItems=[];
   this._vacantDraftId=this.data.draft.draft_id;this._vacantItems=[...(this._vacantItems || []),item];
  }
  getRuntime().outfitStore.excluded(id,true);this.syncDraft();this.setData({reason:'',error:''});
 },
 undoExclude(e){if(v.writable(this)){getRuntime().outfitStore.excluded(String(e.currentTarget.dataset.id),false);this.syncDraft();this.setData({error:''});}},
 generate(){
  if(!v.writable(this))return;
  this.closeItem();const rt=getRuntime(),ticket=rt.outfitStore.requestTicket(),previous=this.data.draft.main_items.map(v.itemId);
  return this.run(async valid=>{
   const result=await rt.outfits.recommend(this.familyId,{...v.payload(this),request_id:ticket.request_id,exclude_combination:previous});
   if(valid() && rt.outfitStore.applyRecommendation(ticket,result)){
    if(result.items && result.items.length)this._vacantItems=[];
    this.syncDraft();this.setData({reason:result.reason || '',error:result.missing && result.missing.length?v.messages(result.missing).join('；'):result.message || ''});this.loadDraftImages();
   }
  },true);
 },
 updateBackupPacking(){this.setData({backupPackingCount:new Set([...(this.data.draft.main_items || []),...(this.data.stagedBackup && this.data.stagedBackup.items || [])].map(v.itemId)).size});},
 openBackup(){
  if(!v.writable(this))return;this.closeItem();this._backupRequest=(this._backupRequest||0)+1;
  const backup=this.data.draft.backup || {mode:'none',items:[]};
  this.setData({backupOpen:true,backupMode:backup.mode,stagedBackup:backup,backupChoices:this.choiceItems(backup.items).map(i=>({...i,selected:true}))});
  this.updateBackupPacking();this.hydrateChoices('backupChoices','_backupRequest');
 },
 backupMode(e){
  if(!v.writable(this))return;const mode=e.currentTarget.dataset.mode;
  if(!['none','partial','full'].includes(mode))return;
  const current=v.ticket(this),request=this._backupRequest=(this._backupRequest||0)+1;
  this.setData({backupMode:mode,backupChoices:[],stagedBackup:{mode,items:[]}});this.updateBackupPacking();
  if(mode==='none')return;
  return this.run(async valid=>{
   const result=await getRuntime().outfits.backup(this.familyId,{...v.payload(this),mode});
   if(valid() && current() && request===this._backupRequest && this.data.backupMode===mode && this.data.backupOpen){
    const choices=this.choiceItems(result.items).map(i=>({...i,selected:mode==='full'}));
    this.setData({backupChoices:choices,stagedBackup:{mode,items:mode==='full'?choices:[]},error:result.message || ''});
    this.updateBackupPacking();this.hydrateChoices('backupChoices','_backupRequest');
   }
  });
 },
 chooseBackup(e){
  if(!v.writable(this) || this.data.backupMode!=='partial')return;
  const id=String(e.currentTarget.dataset.id),key=e.currentTarget.dataset.key;
  const selected=this.data.backupChoices.find(i=>key?i.choiceKey===key:v.itemId(i)===id);if(!selected)return;
  const choices=this.data.backupChoices.map(i=>i.choiceKey===selected.choiceKey?{...i,selected:!i.selected}:v.itemId(i)===id?{...i,selected:false}:i);
  this.setData({backupChoices:choices,stagedBackup:{mode:this.data.backupMode,items:choices.filter(i=>i.selected)}});this.updateBackupPacking();
 },
 confirmBackup(){
  if(!v.writable(this) || this.data.busy || this.data.loading)return;
  const b=this.data.stagedBackup;
  if(!b || b.mode!=='none' && !b.items.length){this.setData({error:'选择需要准备的备用，或明确选择无备用。'});return;}
  const rt=getRuntime();rt.outfitStore.stageBackup(b);rt.outfitStore.confirmBackup();this.syncDraft();
  this._backupRequest=(this._backupRequest||0)+1;this.setData({backupOpen:false,stagedBackup:null,backupChoices:[]});this.loadDraftImages();
 },
 cancelBackup(){
  this._backupRequest=(this._backupRequest||0)+1;
  if(v.writable(this) && !this.data.draftFrozen)getRuntime().outfitStore.cancelBackup();
  this.setData({backupOpen:false,stagedBackup:null,backupChoices:[]});
 },
 removeBackup(){if(v.writable(this)){const rt=getRuntime();rt.outfitStore.stageBackup({mode:'none',items:[]});rt.outfitStore.confirmBackup();this.syncDraft();}},
 review(){
  if(this.data.unknownResult)return navigate('outfit-review','?date='+encodeURIComponent(this.data.targetDate));
  if(this.data.candidateOpen || this.data.backupOpen || this.data.operationOpen){this.setData({error:'请先确认或取消暂存调整。'});return;}v.toReview(this);
 },
 async returnOrigin(){
  if(!v.writable(this))return;
  const current=v.ticket(this);
  if(this.data.draft.dirty && !await confirmation('返回原建议','放弃这份单品发起草稿，恢复此前建议？'))return;
  if(!current() || !v.writable(this))return;
  getRuntime().outfitStore.returnOrigin();this.syncDraft();this.setData({sourceOrigin:false});this.loadDraftImages();
 },
 async back(){
  if(this.data.operationOpen){this.closeItem();return;}
  if(this.data.candidateOpen){this.cancelCandidates();return;}
  if(this.data.backupOpen){this.cancelBackup();return;}
  const current=v.ticket(this);
  if(this.data.draft && this.data.draft.dirty && !await confirmation('离开调整','草稿会保留。确认离开，或取消继续调整。'))return;
  if(current())wx.navigateBack();
 },
 async discard(){
  if(!v.writable(this))return;const current=v.ticket(this);
  if(!await confirmation('放弃本次调整','未保存改动将放弃，已选方案保持。'))return;
  if(!current() || !v.writable(this))return;
  const rt=getRuntime(),original=rt.outfitStore.get();
  return this.run(async valid=>{
   let latest,freshContext;
   if(original.target_plan_id){
    const result=await rt.outfits.context(this.familyId,{child_id:original.child_id,target_date:original.target_date,scene:original.scene,preference_mode:original.preference_mode,designated_member_id:original.designated_member_id,...v.location()});
    if(!valid() || !current())return;
    if(result.role!==undefined){
     rt.session.capability(this.familyId,result.role);
     if(!rt.session.canEdit(this.familyId)){this.onEditRevoked();return;}
    }
    latest=(result.plans || []).find(p=>p.id===original.target_plan_id);freshContext=result;
   }
   if(!valid() || !current() || !v.writable(this))return;
   if(freshContext)this._outfitContext=freshContext;
   rt.outfitStore.discard();
   if(original.target_plan_id && !latest){this.setData({draft:null});wx.reLaunch({url:'/pages/home/home'});return;}
   if(latest)rt.outfitStore.beginEdit(latest);
   this.syncDraft();this.closeItem();this.setData({candidateOpen:false,backupOpen:false,error:'',reason:''});this.loadDraftImages();
  },true);
 },
 preview(e){return v.preview(this,e);},
 async wardrobe(){
  const current=v.ticket(this);
  if(this.data.draft && this.data.draft.dirty && !await confirmation('前往衣橱','草稿会保留。确认离开调整，前往衣橱核对？'))return;
  if(current())wx.reLaunch({url:'/pages/wardrobe/wardrobe'});
 },
 noop(){},
 onEditRevoked(){
  this._knownItems=new Map();this._vacantItems=[];this._candidateRequest=(this._candidateRequest||0)+1;this._backupRequest=(this._backupRequest||0)+1;
  this.closeItem();this.setData({lockedItems:[],excludedItems:[],emptySlots:[],replaceItem:null,backupChoices:[],stagedBackup:null});v.accessRevoked(this);
 }
}));

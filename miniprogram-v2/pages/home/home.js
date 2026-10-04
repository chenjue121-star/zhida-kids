const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,selectChild,membership}=require('../../services/page');
const {ageLabel}=require('../../services/forms');
const {resolveEntry}=require('../../services/entry');
const v=require('../../services/outfit-view');

function locate(){return new Promise((resolve,reject)=>{let settled=false;const finish=(callback,value)=>{if(settled)return;settled=true;clearTimeout(timer);callback(value);};const timer=setTimeout(()=>finish(reject,new Error('定位暂不可用')),5000);wx.getLocation({type:'gcj02',success:value=>finish(resolve,value),fail:error=>finish(reject,error)});});}
Page(definePage({
  data:{planViews:[],childNickname:'',targetDateLabel:'',todayLabel:'',tomorrowLabel:'',backupExpanded:false,children:[],child:null,age:'',family:null,role:null,weather:null,weatherMessage:'',locationLabel:'',mode:'today',switchSheet:false,wardrobeCount:null,wardrobeMessage:'',writable:false,targetDate:'',today:'',draft:null,plans:[],selectedPlan:null,viewSelected:false,contextReady:false,reason:'',warnings:[],missing:[],criteriaSheet:false,scenes:v.scenes,sceneIndex:0,preferenceOptions:['家庭统一偏好','当前使用者偏好','指定成员偏好'],preferenceIndex:0,members:[],memberIndex:0,unknownResult:false},
  errorState:v.errorState,
  onShow(){this._visible=true;if(!getRuntime().session.token()){this.resetHome();return wx.reLaunch({url:'/pages/onboarding/onboarding'});}return this.reload();},
  resetHome(){
    this._load=(this._load||0)+1;this._contextRequest=(this._contextRequest||0)+1;this._outfitEpoch=(this._outfitEpoch||0)+1;this._planRequest=(this._planRequest||0)+1;this._switchRequest=(this._switchRequest||0)+1;this._outfitContext=null;this._location=null;this._criteriaBasis=null;this._criteriaChanged=false;getRuntime().outfitStore.invalidate();
    this.setData({ready:false,busy:false,loading:false,error:'',conflict:false,dailyLoading:false,draft:null,plans:[],selectedPlan:null,viewSelected:false,contextReady:false,child:null,children:[],family:null,role:null,writable:false,switchSheet:false,criteriaSheet:false,members:[],weather:null,weatherMessage:'',locationLabel:'',accessRevoked:false,planViews:[],childNickname:'',childAge:'',childInitial:'',age:'',sceneLabel:'',preferenceLabel:'',targetDate:'',today:'',targetDateLabel:'',dateLabel:'',todayLabel:'',tomorrowLabel:'',unknownResult:false,resumeAvailable:false,reason:'',warnings:[],missing:[],backupExpanded:false});
  },
  async reload(){
    const runtime=getRuntime();const familyId=runtime.session.read('_','family');
    this.resetHome();
    this._weatherEpoch=(this._weatherEpoch || 0)+1;
    if(!familyId){
      try{const target=await resolveEntry(runtime);if(target!=='home')return wx.reLaunch({url:'/pages/'+target+'/'+target});}
      catch(e){this.setData({error:e.message || '读取资料失败'});return;}
    }
    return this.run(async valid=>{
      const fid=runtime.session.read('_','family');
      this.familyId=fid;
      const family=await runtime.api.request('/families/'+encodeURIComponent(fid));
      const children=await runtime.api.request('/families/'+encodeURIComponent(fid)+'/children');
      const info=await membership(fid);
      if(!valid())return;
      runtime.session.write(fid,'children',children);
      const child=children.find(c=>c.id===runtime.session.read(fid,'child')) || children[0] || null;
      const displayChildren=children.map(c=>({...c,initial:c.nickname.slice(0,1),ageLabel:ageLabel(c)}));
      this.setData({family,role:info.role,children:displayChildren,child:child ? displayChildren.find(c=>c.id===child.id) : null,
        age:child?ageLabel(child):'',ready:true,loading:false,writable:['admin','editor'].includes(info.role),members:info.members.filter(m=>m.status==='active')});
      if(child)selectChild(child.id);
      else {runtime.session.remove(fid,'child');runtime.context.select({familyId:fid,childId:null});}
      runtime.session.capability(fid,info.role);
      if(child){this.setData({targetDate:'',mode:runtime.outfitStore.dateMode(fid,child.id)});this.loadWeather();this.loadWardrobe();}
    });
  },
  loadWardrobe(){this.setData({wardrobeCount:null,wardrobeMessage:'正在读取衣橱…'});return this.run(async valid=>{const rt=getRuntime(),fid=rt.session.read('_','family'),childId=rt.session.read(fid,'child');const result=await rt.wardrobe.list(fid,{child_id:childId,limit:1});if(valid())this.setData({wardrobeCount:result.total,wardrobeMessage:''});},false,{background:true});},
  async loadWeather(){
    const rt=getRuntime(),fid=this.familyId || rt.session.read('_','family'),cid=rt.session.read(fid,'child');if(!fid||!cid)return;
    const epoch=this._outfitEpoch=(this._outfitEpoch||0)+1,generation=rt.session.generation(),ticket=rt.context.capture();
    const current=()=>this._visible!==false && epoch===this._outfitEpoch && generation===rt.session.generation() && rt.context.isCurrent(ticket);
    rt.outfitStore.invalidate();this.setData({dailyLoading:true,weatherMessage:'正在获取目标日预报…'});
    if(!v.location().city){try{const loc=await locate();if(!current())return;this._location={lat:loc.latitude,lon:loc.longitude};}catch(e){if(!current())return;this._location={};}}
    try{const result=await v.refreshContext(this,{dateMode:this.data.mode,basisOverride:this._criteriaBasis});if(!current())return;
      const saved=rt.session.read(fid,'outfit-view:'+cid+':'+result.target_date),plan=(result.plans||[]).find(p=>p.id===saved) || (result.plans||[])[0];
      this.setData({selectedPlan:plan||null,viewSelected:!!plan,locationLabel:result.weather && result.weather.city || v.location().city || this.data.family && this.data.family.city || '家庭地点',weatherMessage:result.weather && result.weather.status==='known'?'':'目标日天气未知，请家长核对适宜性。',warnings:[],missing:[],unknownResult:!!rt.outfits.pending(fid,result.target_date,cid)});this.planSummaries();
      if(plan && !this._criteriaChanged){const current=rt.outfitStore.get();this.setData({resumeAvailable:!!(current && current.dirty && current.status!=='completed')});this.showPlan(plan);return;}
      if(!this.data.writable){this.setData({draft:result.suggestion?v.draftView({main_items:result.suggestion.items,backup:{mode:'none',items:[]}}):null,reason:result.suggestion && result.suggestion.reason || '',warnings:v.messages(result.suggestion && result.suggestion.warnings || [])});v.images(this);return;}
      this.setData({viewSelected:false,selectedPlan:null});v.sync(this);this.setData({reason:this.data.draft.reason || '',warnings:v.messages(this.data.draft.warnings||[]),missing:v.messages(this.data.draft.missing||[]),resumeAvailable:!!(this.data.draft.dirty && this.data.draft.status!=='completed')});const criteriaChanged=this._criteriaChanged;this._criteriaChanged=false;this._criteriaBasis=null;if(criteriaChanged)await this.changeOutfit(false);else if(!this.data.draft.main_items.length){if(result.suggestion && rt.outfitStore.adoptSuggestion(result.suggestion)){v.sync(this);this.setData({reason:result.suggestion.reason || '',warnings:v.messages(result.suggestion.warnings || []),missing:v.messages(result.suggestion.missing || [])});}else await this.changeOutfit(false);}
      this.setData({warnings:[...this.data.warnings,...v.currentWarnings(this)].filter((x,i,a)=>a.indexOf(x)===i)});v.images(this);
    }catch(e){if(this.handleAccessError(e,generation))return;if(current() && e.code!=='STALE')this.setData({error:e.message || '目标日搭配暂不可用，当前草稿已保留。'});}
    finally{if(current())this.setData({dailyLoading:false});}
  },
  showPlan(plan){this.setData({...v.contextLabels(this,plan),selectedPlan:plan,viewSelected:true,draft:v.draftView({...plan,draft_id:'selected:'+plan.id,revision:plan.version},this._outfitContext && this._outfitContext.garments),reason:'',warnings:v.messages(plan.current_warnings || []),missing:[],backupExpanded:false});v.images(this);},
  async planSummaries(){
    const rt=getRuntime(),plans=this.data.plans||[],request=this._planRequest=(this._planRequest||0)+1,current=v.ticket(this,{draft:false});
    const views=plans.map(plan=>({id:plan.id,sequence:plan.sequence,selected_by:plan.selected_by||'家人',backupLabel:plan.backup && plan.backup.items.length?'带备用':'无备用',mainSummary:(plan.main_items||[]).map(i=>i.name||v.items([i])[0].categoryLabel).join('、'),photoItems:v.items((plan.main_items||[]).slice(0,3)),updatedLabel:this.updatedLabel(plan.updated_at)}));
    this.setData({planViews:views});
    for(const plan of views)for(const item of plan.photoItems){if(!item.asset_id)continue;try{const image=await rt.media.image(this.familyId,item.asset_id);if(!current() || request!==this._planRequest)return;item.image=image;this.setData({planViews:views.map(p=>({...p,photoItems:p.photoItems.map(i=>({...i}))}))});}catch(e){if(this.handleAccessError(e,rt.session.generation()))return;}}
  },
  updatedLabel(value){if(!value)return '家人已选';try{const date=new Date(value);if(Number.isNaN(date.getTime()))return '家人已选';const formatter=new Intl.DateTimeFormat('zh-CN',{timeZone:this.data.timezone||'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});return formatter.format(date)+' 更新';}catch(e){return '家人已更新';}},
  openItem(e){if(this.data.viewSelected || !v.writable(this))return this.preview(e);const id=String(e.currentTarget.dataset.id);if((this.data.draft && this.data.draft.main_items||[]).some(i=>v.itemId(i)===id))navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate)+'&item='+encodeURIComponent(id)+'&usage=main');},
  toggleBackup(){this.setData({backupExpanded:!this.data.backupExpanded});},

  choosePlan(e){if(!this.data.ready)return;const p=this.data.plans.find(p=>p.id===String(e.currentTarget.dataset.id));if(p){this._load=(this._load||0)+1;this._outfitEpoch=(this._outfitEpoch||0)+1;getRuntime().outfitStore.invalidate();this.setData({busy:false,loading:false,dailyLoading:false});getRuntime().session.write(this.familyId,'outfit-view:'+this.data.child.id+':'+this.data.targetDate,p.id);this.showPlan(p);this.planSummaries();}},
  mode(e){const rt=getRuntime(),mode=e.currentTarget.dataset.mode;if(!this.data.child)return;rt.outfitStore.setDateMode(this.familyId,this.data.child.id,mode);this.clearDaily();this.setData({mode,targetDate:'',contextReady:false});return this.loadWeather();},
  changeOutfit(explicit=true){if(!v.writable(this)||this.data.viewSelected || this.data.busy)return;const rt=getRuntime(),ticket=rt.outfitStore.requestTicket(),old=rt.outfitStore.get(),epoch=this._outfitEpoch;return this.run(async valid=>{const result=await rt.outfits.recommend(this.familyId,{...v.payload(this),request_id:ticket.request_id,exclude_combination:explicit?old.main_items.map(v.itemId):[]});if(valid() && epoch===this._outfitEpoch && rt.outfitStore.applyRecommendation(ticket,result)){v.sync(this);this.setData({reason:result.reason || '',warnings:v.messages(result.warnings || []),missing:v.messages(result.missing || []),error:result.message || ''});v.images(this);}},true);},
  adjust(){if(v.writable(this)&&!this.data.viewSelected)navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate));},
  selectOutfit(){if(v.writable(this)&&!this.data.viewSelected)v.toReview(this);},
  async editPlan(){if(v.writable(this)&&this.data.selectedPlan){const d=getRuntime().outfitStore.get();if(d && d.dirty && !await require('../../services/page').confirmation('重新编辑已选','放弃保留中的未保存草稿，从这套已选重新开始？'))return;getRuntime().outfitStore.beginEdit(this.data.selectedPlan,false);navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate));}},
  async addPlan(){if(v.writable(this)&&this.data.selectedPlan){const d=getRuntime().outfitStore.get();if(d && d.dirty && !await require('../../services/page').confirmation('新增一套','放弃保留中的未保存草稿，从这套已选创建另一套？'))return;getRuntime().outfitStore.beginEdit(this.data.selectedPlan,true);navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate));}},
  resumeDraft(){if(v.writable(this))navigate('outfit-edit','?date='+encodeURIComponent(this.data.targetDate));},
  resumeSave(){if(this.data.targetDate)navigate('outfit-review','?date='+encodeURIComponent(this.data.targetDate));},
  criteria(){if(!v.writable(this))return;const d=(this.data.viewSelected?this.data.selectedPlan:getRuntime().outfitStore.get()) || this.data.draft || {},subject=d.preference_subject || {};this.setData({criteriaSheet:true,sceneIndex:Math.max(0,v.scenes.findIndex(x=>x.key===d.scene)),preferenceIndex:Math.max(0,['family','current_member','designated_member'].indexOf(d.preference_mode || subject.mode || 'family')),memberIndex:Math.max(0,this.data.members.findIndex(x=>String(x.id)===String(d.designated_member_id || subject.membership_id)))});},closeCriteria(){this.setData({criteriaSheet:false});},
  scene(e){this.setData({sceneIndex:Number(e.detail.value)});},preference(e){this.setData({preferenceIndex:Number(e.detail.value)});},member(e){this.setData({memberIndex:Number(e.detail.value)});},
  async applyCriteria(){if(!v.writable(this)||this.data.unknownResult)return;const mode=['family','current_member','designated_member'][this.data.preferenceIndex],member=this.data.members[this.data.memberIndex];if(mode==='designated_member'&&!member){this.setData({error:'请选择本家庭的有效成员。'});return;}const rt=getRuntime(),scene=v.scenes[this.data.sceneIndex].key;if(this.data.viewSelected && this.data.selectedPlan){const prior=rt.outfitStore.get();if(prior && prior.dirty && !await require('../../services/page').confirmation('准备新建议','放弃保留中的未保存调整，从已选方案准备新的建议？'))return;rt.outfitStore.beginEdit(this.data.selectedPlan,true);}this._load=(this._load||0)+1;this.setData({busy:false,loading:false});const basis={scene,preference_mode:mode,designated_member_id:mode==='designated_member'?member.id:null};rt.session.write(this.familyId,'outfit-basis:'+this.data.child.id,basis);this._criteriaBasis=basis;this._criteriaChanged=true;this.setData({criteriaSheet:false});return this.loadWeather();},
  preview(e){return v.preview(this,e);},onEditRevoked(){v.accessRevoked(this);},
  onHide(){this._visible=false;this._load=(this._load||0)+1;this._outfitEpoch=(this._outfitEpoch||0)+1;getRuntime().outfitStore.invalidate();},onUnload(){this.onHide();},
  async openChildSwitch(){
    if(!this.data.ready || !this.data.children.length)return;
    const rt=getRuntime(),current=v.ticket(this,{draft:false}),request=this._switchRequest=(this._switchRequest||0)+1,children=this.data.children.map(c=>({...c,todaySummary:'正在读取今天安排…'}));
    this.setData({switchSheet:true,children});
    await Promise.all(children.map(async child=>{
      try{const result=await rt.outfits.context(this.familyId,{child_id:child.id,...(this.data.today?{target_date:this.data.today}:{date_mode:'today'}),scene:'daily',preference_mode:'family',...v.location()});
        if(!current() || request!==this._switchRequest || !this.data.switchSheet)return;
        const count=(result.plans||[]).length;this.setData({children:this.data.children.map(c=>c.id===child.id?{...c,todaySummary:count?'今天已选 · '+count+'套':'今天待选'}:c)});
      }catch(e){if(this.handleAccessError(e,rt.session.generation()))return;if(current() && request===this._switchRequest && this.data.switchSheet)this.setData({children:this.data.children.map(c=>c.id===child.id?{...c,todaySummary:'今天安排暂不可用'}:c)});}
    }));
  },
  closeChildSwitch(){this._switchRequest=(this._switchRequest||0)+1;this.setData({switchSheet:false});},
  noop(){},
  clearDaily(){this._switchRequest=(this._switchRequest||0)+1;this._planRequest=(this._planRequest||0)+1;this._load=(this._load||0)+1;this._criteriaChanged=false;this._criteriaBasis=null;this._outfitEpoch=(this._outfitEpoch||0)+1;getRuntime().outfitStore.invalidate();this._outfitContext=null;this.setData({busy:false,loading:false,dailyLoading:false,draft:null,plans:[],selectedPlan:null,viewSelected:false,weather:null,weatherMessage:'',locationLabel:'',reason:'',warnings:[],missing:[],contextReady:false,resumeAvailable:false,unknownResult:false,criteriaSheet:false,planViews:[],childNickname:'',sceneLabel:'',preferenceLabel:'',todayLabel:'',tomorrowLabel:'',backupExpanded:false});},
  choose(e){
    if(!this.data.ready)return;
    const child=this.data.children.find(c=>c.id===e.currentTarget.dataset.id);
    if(!child)return;
    selectChild(child.id);this.clearDaily();
    this.setData({child,age:child.ageLabel,switchSheet:false,targetDate:'',mode:getRuntime().outfitStore.dateMode(this.familyId || getRuntime().session.read('_','family'),child.id)});
    this.loadWardrobe();this.loadWeather();
  },
  editChild(e){
    if(!this.data.ready)return;
    this.closeChildSwitch();navigate('child-edit','?id='+encodeURIComponent(e.currentTarget.dataset.id));
  },
  addChild(){if(this.data.ready && ['admin','editor'].includes(this.data.role)){this.closeChildSwitch();navigate('child-edit');}},
  children(){this.closeChildSwitch();navigate('children');},
  families(){navigate('families');},
  familyDetail(){if(this.data.ready && this.familyId)navigate('family-detail','?id='+encodeURIComponent(this.familyId));},
  location(){navigate('location');},
  my(){navigate('my');},
  calendar(){wx.reLaunch({url:'/pages/calendar/calendar'});},
  wardrobe(){wx.reLaunch({url:'/pages/wardrobe/wardrobe'});},
  addClothes(){if(this.data.ready && this.data.child && ['admin','editor'].includes(this.data.role))navigate('intake');},
  home(){},
  retry(){this.reload();}
}));

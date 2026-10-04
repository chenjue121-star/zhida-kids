const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,requireLogin,selectFamily,confirmation,membership}=require('../../services/page');
const {styles,defaultSettings,settingsPayload}=require('../../services/forms');
const {inferredView}=require('../../services/calendar-view');
Page(definePage({
  data:{
    role:null,child:null,childInitial:'宝',members:[],profileTab:'family',profiles:null,styleOptions:styles,selectedStyles:[],
    memberPreview:null,previewMemberId:null,previewStyles:[],previewLoading:false,previewError:'',
    inferredTags:[],evidenceTag:null,memberInferredTags:[],profileNote:'',
    form:{...defaultSettings,version:0},modeIndex:0,thermalIndex:0,fitIndex:0,neckIndex:0,memberIndex:0,
    modeOptions:[{key:'family',label:'家庭共同偏好'},{key:'designated_member',label:'指定成员偏好'},{key:'current_member',label:'当前使用者偏好'}],
    thermalOptions:[{key:'unknown',label:'未知'},{key:'neutral',label:'适中'},{key:'runs_warm',label:'容易怕热'},{key:'runs_cold',label:'容易怕冷'}],
    fitOptions:[{key:'unknown',label:'未知'},{key:'regular',label:'常规合身'},{key:'loose',label:'宽松'}],
    neckOptions:[{key:null,label:'未知'},{key:true,label:'避免高领'},{key:false,label:'不避高领'}]
  },
  onLoad(options) {this.childId=options.id;this.familyId=getRuntime().session.read('_','family');},
  onShow() {
    this._visible=true;this.setData({busy:false});
    if(!requireLogin())return;
    const {session}=getRuntime();
    if(!this.familyId || !this.childId || session.read('_','family')!==this.familyId){this.clearPrivate();return navigate('families','',true);}
    const owner=session.user().id+':'+this.familyId;
    if(this.owner && this.owner!==owner){this.clearPrivate();return navigate('families','',true);}
    this.owner=owner;selectFamily(this.familyId);
    if(!this.data.ready)this.reload();
    else this.refreshVersions();
  },
  clearPrivate(){this._styleDrafts={};this.clearMemberPreview();this.setData({ready:false,child:null,profiles:null,selectedStyles:[],inferredTags:[],evidenceTag:null,memberInferredTags:[],members:[],form:{...defaultSettings,version:0}});},
  path() {return '/families/'+encodeURIComponent(this.familyId)+'/children/'+encodeURIComponent(this.childId);},
  reload() {
    this._styleDrafts={};this._settingsDirty=false;
    this.clearMemberPreview();
    this.setData({ready:false});
    return this.run(async valid=>{
      const {api,session}=getRuntime();
      const info=await membership(this.familyId);
      if(!valid())return;session.capability(this.familyId,info.role);
      const child=await api.request(this.path());
      const settings=await api.request(this.path()+'/preference-settings');
      const family=await api.request(this.path()+'/profiles/family');
      const me=await api.request(this.path()+'/profiles/me');
      if(!valid())return;
      const members=info.members.filter(m=>m.status==='active').map(m=>({...m,label:m.nickname || '家庭成员 '+m.id}));
      this.setData({role:info.role,child,childInitial:(child.nickname || '宝').slice(0,1),members,profiles:{family,me},ready:true});
      this.applySettings(settings);this.applyProfile(this.data.profileTab);
    });
  },
  refreshVersions(){return this.run(async valid=>{
    const rt=getRuntime(),info=await membership(this.familyId);if(!valid())return;rt.session.capability(this.familyId,info.role);this.setData({role:info.role,members:info.members.filter(m=>m.status==='active').map(m=>({...m,label:m.nickname || '家庭成员 '+m.id}))});
    const [family,me,settings]=await Promise.all([rt.api.request(this.path()+'/profiles/family'),rt.api.request(this.path()+'/profiles/me'),rt.api.request(this.path()+'/preference-settings')]);if(!valid())return;
    let changed=false;for(const [tab,next] of [['family',family],['me',me]]){const old=this.data.profiles[tab],draft=this._styleDrafts && this._styleDrafts[tab];if(draft && JSON.stringify(draft)!==JSON.stringify(old.styles) && old.version!==next.version){changed=true;this.setData({['profiles.'+tab]:{...next,version:old.version}});}else this.setData({['profiles.'+tab]:next});}
    if(this._settingsDirty && settings.version!==this.data.form.version)changed=true;else if(!this._settingsDirty)this.applySettings(settings);
    this.applyProfile(this.data.profileTab);if(changed)this.setData({conflict:true,error:'家人已更新偏好。未保存的填写已保留，请重新加载后核对。'});return this.loadMemberPreview();
  });},
  applySettings(settings) {
    this.setData({form:settings,modeIndex:this.data.modeOptions.findIndex(o=>o.key===settings.mode),
      thermalIndex:this.data.thermalOptions.findIndex(o=>o.key===settings.thermal_preference),
      fitIndex:this.data.fitOptions.findIndex(o=>o.key===settings.fit_preference),
      neckIndex:this.data.neckOptions.findIndex(o=>o.key===settings.avoid_high_neck),
      memberIndex:Math.max(0,this.data.members.findIndex(m=>m.id===settings.designated_member_id))});
    this.loadMemberPreview();
  },
  applyProfile(tab) {
    const selected=this._styleDrafts && this._styleDrafts[tab] || this.data.profiles[tab].styles;
    this.setData({profileTab:tab,selectedStyles:selected,styleOptions:styles.map(s=>({...s,checked:selected.includes(s.key)})),inferredTags:inferredView(this.data.profiles[tab]),evidenceTag:null});
  },
  tab(e) {
    if(this.data.busy || !this.data.profiles || !['family','me'].includes(e.currentTarget.dataset.tab))return;
    const tab=e.currentTarget.dataset.tab;
    this._styleDrafts=this._styleDrafts || {};this._styleDrafts[this.data.profileTab]=[...this.data.selectedStyles];
    this.applyProfile(tab);
  },
  option(e) {
    this._settingsDirty=true;
    const name=e.currentTarget.dataset.name;const index=Number(e.detail.value);
    const field={mode:'mode',thermal:'thermal_preference',fit:'fit_preference',neck:'avoid_high_neck'}[name];
    const key=this.data[name+'Options'][index].key;
    this.setData({[name+'Index']:index,['form.'+field]:key});
    if(name==='mode') {
      const memberIndex=Math.max(0,this.data.members.findIndex(m=>m.id===this.data.form.designated_member_id));
      this.setData({memberIndex,'form.designated_member_id':key==='designated_member' ? ((this.data.members[memberIndex] || {}).id || null):null});
      this.loadMemberPreview();
    }
  },
  member(e) {
    this._settingsDirty=true;
    const index=Number(e.detail.value);if(!this.data.members[index])return;
    this.setData({memberIndex:index,'form.designated_member_id':this.data.members[index].id});
    return this.loadMemberPreview();
  },
  clearMemberPreview() {
    this._previewEpoch=(this._previewEpoch || 0)+1;
    this.setData({memberPreview:null,previewMemberId:null,previewStyles:[],memberInferredTags:[],previewLoading:false,previewError:''});
  },
  loadMemberPreview() {
    this.clearMemberPreview();
    const id=this.data.form.designated_member_id;
    if(this.data.form.mode!=='designated_member' || !this.data.members.some(m=>m.id===id))return;
    const epoch=this._previewEpoch;
    this.setData({previewMemberId:id,previewLoading:true});
    return this.run(async valid=>{
      const current=()=>valid() && epoch===this._previewEpoch;
      try {
        const profile=await getRuntime().api.request(this.path()+'/profiles/members/'+encodeURIComponent(id));
        if(current())this.setData({memberPreview:profile,previewStyles:styles.filter(s=>profile.styles.includes(s.key)),memberInferredTags:inferredView(profile)});
      } catch(e) {
        if(e.code==='FAMILY_ACCESS_REVOKED')throw e;
        if(current() && e.code!=='STALE')this.setData({previewError:e.message || '无法读取成员偏好'});
      } finally {if(current())this.setData({previewLoading:false});}
    },false,{background:true});
  },
  styles(e) {if(this.data.role==='viewer')return;const selected=e.detail.value;this._styleDrafts=this._styleDrafts || {};this._styleDrafts[this.data.profileTab]=[...selected];this.setData({selectedStyles:selected,styleOptions:styles.map(s=>({...s,checked:selected.includes(s.key)}))});},
  noStyles() {if(this.data.role==='viewer')return;this._styleDrafts=this._styleDrafts || {};this._styleDrafts[this.data.profileTab]=[];this.setData({selectedStyles:[],styleOptions:styles.map(s=>({...s,checked:false}))});},
  evidence(e){const tag=this.data.inferredTags.find(t=>t.style===e.currentTarget.dataset.style);if(tag)this.setData({evidenceTag:tag});},
  closeEvidence(){this.setData({evidenceTag:null});},
  evidencePlan(e){navigate('plan-detail','?id='+encodeURIComponent(e.currentTarget.dataset.id));},
  tagAction(e){if(!this.data.ready || !['admin','editor'].includes(this.data.role) || this.data.busy || this.data.conflict)return;const {style,action}=e.currentTarget.dataset;if(!['accept','dismiss'].includes(action) || action==='accept' && this.data.inferredTags.some(t=>t.style===style && !t.canAccept))return;const tab=this.data.profileTab,old=this.data.profiles[tab],draft=this._styleDrafts && this._styleDrafts[tab],dirty=draft && JSON.stringify(draft)!==JSON.stringify(old.styles);return this.run(async valid=>{const profile=await getRuntime().plans.tag(this.familyId,this.childId,tab,style,{expected_version:old.version,action});if(!valid())return;this.setData({['profiles.'+tab]:profile});if(!dirty && this._styleDrafts)delete this._styleDrafts[tab];this.applyProfile(tab);wx.showToast({title:action==='accept'?'已采纳为明确偏好':'推断已移除',icon:'none'});},true);},
  editInferred(e){if(!['admin','editor'].includes(this.data.role))return;const tag=this.data.inferredTags.find(t=>t.style===e.currentTarget.dataset.style);if(!tag)return;this.setData({evidenceTag:null,profileNote:'正在编辑'+tag.label+'。请调整明确风格并保存；推断仍可单独移除。'});if(wx.pageScrollTo)wx.pageScrollTo({scrollTop:0,duration:200});},
  saveProfile() {
    if(!this.data.ready || this.data.conflict || !['admin','editor'].includes(this.data.role) || !getRuntime().session.canEdit(this.familyId) || !['family','me'].includes(this.data.profileTab))return;
    return this.run(async valid=>{
      const tab=this.data.profileTab;
      const profile=await getRuntime().api.request(this.path()+'/profiles/'+tab,{method:'PUT',editScope:true,data:{
        styles:this.data.selectedStyles,expected_version:this.data.profiles[tab].version
      }});
      if(valid()){if(this._styleDrafts)delete this._styleDrafts[tab];this.setData({['profiles.'+tab]:profile});this.applyProfile(tab);wx.showToast({title:'风格已保存',icon:'success'});}
    },true);
  },
  saveSettings() {
    if(!this.data.ready || this.data.conflict || !['admin','editor'].includes(this.data.role) || !getRuntime().session.canEdit(this.familyId))return;
    return this.run(async valid=>{
      const settings=await getRuntime().api.request(this.path()+'/preference-settings',{method:'PUT',editScope:true,data:settingsPayload(this.data.form)});
      if(valid()){this._settingsDirty=false;this.applySettings(settings);wx.showToast({title:'设置已保存',icon:'success'});}
    },true);
  },
  onEditRevoked(){this.setData({role:'viewer',evidenceTag:null});this.clearMemberPreview();if(getRuntime().session.capability(this.familyId).role===null)this.clearPrivate();},
  noop(){},
  async reloadConfirm() {if(await confirmation('重新加载','将丢弃未保存的偏好修改，获取最新内容。'))this.reload();}
}));

const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,requireLogin,selectFamily,confirmation,membership,roles}=require('../../services/page');
Page(definePage({
  data:{family:null,members:[],adminCount:0,role:null,form:{name:'',city:'',timezone:''},profileOpen:false,memberOpenId:null,inviteRoles:['可编辑','仅查看'],inviteRole:0,invitation:null,roleOptions:['管理员','可编辑','仅查看'],inviteOpen:false,pendingAction:null,actionError:''},
  onLoad(options) { this.familyId=options.id || getRuntime().session.read('_','family'); },
  onShow() {
    this._visible=true; this.setData({busy:false});
    if (!requireLogin()) return;
    if (!this.familyId) return navigate('families','',true);
    selectFamily(this.familyId); this.reload();
  },
  path() { return '/families/'+encodeURIComponent(this.familyId); },
  reload() {
    this.setData({ready:false});
    return this.run(async valid=>{
      const {api,session}=getRuntime();
      const family=await api.request(this.path());
      const info=await membership(this.familyId);
      if (!valid()) return;
      const members=info.members.filter(m=>m.status==='active').map(m=>({...m,roleLabel:roles[m.role],isSelf:m.user_id===session.user().id,roleIndex:['admin','editor','viewer'].indexOf(m.role),initial:(m.nickname || '家').slice(0,1)}));
      this.setData({family,members,adminCount:members.filter(m=>m.role==='admin').length,role:info.role,ready:true,memberOpenId:null,pendingAction:null,actionError:'',form:{name:family.name,city:family.city,timezone:family.timezone}});
    });
  },
  async reloadConfirm() { if(await confirmation('重新加载','将丢弃未保存的家庭修改，获取最新内容。')) this.reload(); },
  toggleProfile(){if(this.data.ready && !this.data.busy)this.setData({profileOpen:!this.data.profileOpen});},
  toggleMember(e){const id=e.currentTarget.dataset.id,member=this.data.members.find(m=>m.id===id);if(this.data.ready && this.data.role==='admin' && !this.data.busy && !this.data.conflict && member && !(member.isSelf && member.role==='admin' && this.activeAdmins()<=1))this.setData({memberOpenId:this.data.memberOpenId===id?null:id});},
  save() {
    if (this.data.role!=='admin' || !this.data.ready || this.data.conflict) return;
    return this.run(async valid=>{
      const family=await getRuntime().api.request(this.path(),{method:'PUT',data:{...this.data.form,expected_version:this.data.family.version}});
      if(valid()) {this.setData({family,form:{name:family.name,city:family.city || '',timezone:family.timezone}});wx.showToast({title:'已保存',icon:'success'});}
    },true);
  },
  inviteRole(e) { this.setData({inviteRole:Number(e.detail.value)}); },
  showInvite(){if(this.data.ready && this.data.role==='admin')this.setData({inviteOpen:!this.data.inviteOpen});},
  createInvitation() {
    if(this.data.role!=='admin' || !this.data.ready || this.data.busy || this.data.conflict)return;
    return this.run(async valid=>{
      const result=await getRuntime().api.request(this.path()+'/invitations',{method:'POST',data:{role:this.data.inviteRole===0?'editor':'viewer'}});
      if(valid()) this.setData({invitation:result,invitationRole:this.data.inviteRoles[this.data.inviteRole]});
    },true);
  },
  onShareAppMessage() {
    const invitation=this.data.invitation;
    return invitation ? {title:'邀请你加入'+this.data.family.name,path:'/pages/invitation/invitation?token='+encodeURIComponent(invitation.token)} :
      {title:'智搭',path:'/pages/login/login'};
  },
  revoke() {
    if(!this.data.invitation || this.data.role!=='admin' || !this.data.ready || this.data.busy)return;
    return this.run(async valid=>{
      await getRuntime().api.request(this.path()+'/invitations/'+encodeURIComponent(this.data.invitation.invitation_id),{method:'DELETE'});
      if(valid()) this.setData({invitation:null});
    },true);
  },
  activeAdmins(){return this.data.members.filter(m=>m.role==='admin' && m.status!=='inactive').length;},
  changeRole(e) {
    const member=this.data.members.find(m=>m.id===e.currentTarget.dataset.id);
    const role=['admin','editor','viewer'][Number(e.detail.value)];
    if(!this.data.ready || !member || !role || role===member.role || this.data.role!=='admin' || this.data.busy || this.data.conflict)return;
    if(member.role==='admin' && role!=='admin' && this.activeAdmins()<=1)return this.setData({actionError:'必须保留至少一位家庭管理员。'});
    this.setData({actionError:'',pendingAction:{type:'role',memberId:member.id,role,
      title:'更改成员权限？',copy:'将'+(member.nickname || '该成员')+'设为'+roles[role]+'。权限变更后立即生效。',confirmLabel:'确认更改'}});
  },
  remove(e) {
    const member=this.data.members.find(m=>m.id===e.currentTarget.dataset.id);
    if(!this.data.ready || !member || member.isSelf || this.data.role!=='admin' || this.data.busy || this.data.conflict)return;
    if(member.role==='admin' && this.activeAdmins()<=1)return this.setData({actionError:'必须保留至少一位家庭管理员。'});
    this.setData({actionError:'',pendingAction:{type:'remove',memberId:member.id,title:'移除家庭成员？',
      copy:'移除'+(member.nickname || '该成员')+'后，对方将不能查看此家庭。其指定偏好会恢复为家庭共同偏好。',confirmLabel:'确认移除'}});
  },
  leave() {
    if(!this.data.ready || !['admin','editor','viewer'].includes(this.data.role) || this.data.busy || this.data.conflict)return;
    if(this.data.role==='admin' && this.activeAdmins()<=1)return this.setData({actionError:'你是最后一位管理员，请先邀请或设置另一位管理员。'});
    this.setData({actionError:'',pendingAction:{type:'leave',title:'退出这个家庭？',
      copy:'退出后你将无法查看此家庭的宝贝档案，重新加入需要家人邀请。',confirmLabel:'确认退出'}});
  },
  closeAction(){if(!this.data.busy)this.setData({pendingAction:null});},
  noop(){},
  async confirmAction(){
    const action=this.data.pendingAction;
    if(!action || !this.data.ready || !['admin','editor','viewer'].includes(this.data.role) || this.data.busy || this.data.conflict)return;
    if(action.type!=='leave' && this.data.role!=='admin')return;
    if(action.type==='leave' && this.data.role==='admin' && this.activeAdmins()<=1)return this.setData({pendingAction:null,actionError:'必须保留至少一位家庭管理员。'});
    if(action.type==='role'){
      const member=this.data.members.find(m=>m.id===action.memberId);
      if(!member || (member.role==='admin' && action.role!=='admin' && this.activeAdmins()<=1))return this.setData({pendingAction:null,actionError:'必须保留至少一位家庭管理员。'});
    }
    await this.run(async valid=>{
      const {api,session,context}=getRuntime();
      if(action.type==='role')await api.request(this.path()+'/members/'+encodeURIComponent(action.memberId),
        {method:'PUT',data:{role:action.role,expected_family_version:this.data.family.version}});
      else if(action.type==='remove')await api.request(this.path()+'/members/'+encodeURIComponent(action.memberId),{method:'DELETE'});
      else await api.request(this.path()+'/leave',{method:'POST'});
      if(!valid())return;
      this.setData({pendingAction:null});
      if(action.type==='leave'){
        session.remove('_','family');session.remove('_','families');session.remove(this.familyId,'children');session.remove(this.familyId,'child');
        context.clear();navigate('families','',true);
      }else await this.reload();
    },true);
    if(this.data.error)this.setData({pendingAction:null});
  }
}));

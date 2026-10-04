const { getRuntime } = require('../../services/runtime');
const { definePage, navigate, requireLogin, selectFamily, confirmation, roles } = require('../../services/page');
Page(definePage({
  data: { families: [], form: { name: '', city: '' }, hasCache: false, mode:'list' },
  onLoad(options={}) {this.setData({mode:options.mode==='create'?'create':'list'});},
  onShow() { this._visible=true; this.setData({busy:false}); if (requireLogin()) this.reload(); },
  reload() {
    const {session,api}=getRuntime();
    const cached=session.read('_','families');
    if (cached) this.setData({families:cached,hasCache:true,cached:true,ready:false});
    return this.run(async valid=>{
      const result=await api.request('/me');
      if (!valid()) return;
      const families=result.families.map(f=>{
        const m=result.memberships.find(m=>m.family_id===f.id && m.status==='active');
        return {...f,roleLabel:roles[m && m.role] || '成员'};
      });
      session.write('_','families',families);
      this.setData({families,ready:true,cached:false,hasCache:true});
    });
  },
  open(e) { if (!this.data.ready || this.data.busy) return; selectFamily(e.currentTarget.dataset.id); wx.reLaunch({url:'/pages/home/home'}); },
  newFamily(){if(this.data.ready && !this.data.busy)this.setData({mode:'create',error:''});},
  cancelCreate(){if(!this.data.busy)this.setData({mode:'list',error:''});},
  create() {
    return this.run(async valid=>{
      const {api,session}=getRuntime();
      const payload={name:this.data.form.name.trim(),city:this.data.form.city.trim() || null};
      if (!payload.name) throw new Error('请填写家庭名称');
      const result=await api.request('/families',{method:'POST',data:payload,
        idempotencyKey:session.mutationKey('_','create-family',payload)});
      if (!valid()) return;
      session.completeMutation('_','create-family');
      this.setData({form:{name:'',city:''},mode:'list'}); selectFamily(result.id); wx.reLaunch({url:'/pages/home/home'});
    },true);
  },
  async logout() {
    if (await confirmation('退出登录','将清除当前账号在此设备上的本地记录。')) {
      getRuntime().session.logout(); wx.reLaunch({url:'/pages/login/login'});
    }
  }
}));

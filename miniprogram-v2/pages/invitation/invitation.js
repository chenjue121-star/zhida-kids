const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,requireLogin,selectFamily,roles}=require('../../services/page');
Page(definePage({
  data:{preview:null,unavailable:false},
  onLoad(options) {
    if(options.token) getRuntime().session.pending(options.token);
  },
  onShow() {
    this._visible=true;this.setData({busy:false});
    if(requireLogin()) this.reload();
  },
  reload() {
    this.setData({preview:null,ready:false,unavailable:false});
    return this.run(async valid=>{
      const {api,session}=getRuntime(); const token=session.pending();
      if(!token)return this.setData({unavailable:true,error:'邀请链接无效，请向家庭管理员索取新邀请'});
      let preview;
      try{preview=await api.request('/invitations/preview',{method:'POST',data:{token}});}
      catch(e){if(e.status===410 || e.status===404){if(valid())this.setData({unavailable:true,error:e.message || '邀请已失效，请向家人索取新邀请'});return;}throw e;}
      if(valid()) this.setData({preview:{...preview,roleLabel:roles[preview.role]},ready:true});
    });
  },
  accept() {
    if(!this.data.ready || this.data.unavailable || !this.data.preview || this.data.busy) return;
    return this.run(async valid=>{
      const {api,session}=getRuntime();
      let result;
      try{result=await api.request('/invitations/accept',{method:'POST',data:{token:session.pending()}});}
      catch(e){if(e.status===410 || e.status===404){if(valid())this.setData({unavailable:true,preview:null,ready:false,error:e.message || '邀请已失效，请向家人索取新邀请'});return;}throw e;}
      if(!valid()) return;
      session.pending(null); selectFamily(result.family_id); wx.reLaunch({url:'/pages/home/home'});
    },true);
  },
  cancel() { getRuntime().session.pending(null); navigate('families','',true); }
}));

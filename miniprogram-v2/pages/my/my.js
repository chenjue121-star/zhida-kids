const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,confirmation}=require('../../services/page');
Page(definePage({
  data:{user:null,families:[],child:null},
  onShow(){this._visible=true;if(!getRuntime().session.token())return wx.reLaunch({url:'/pages/login/login'});this.reload();},
  reload(){this.setData({ready:false,user:null,child:null,families:[]});return this.run(async valid=>{
    const runtime=getRuntime();const me=await runtime.api.request('/me');
    const fid=runtime.session.read('_','family');
    const accessible=!!fid && (me.families || []).some(f=>f.id===fid);
    this.familyId=accessible?fid:null;
    const children=accessible?await runtime.api.request('/families/'+encodeURIComponent(fid)+'/children'):[];
    if(!valid())return;
    const child=accessible?(children.find(c=>c.id===runtime.session.read(fid,'child')) || children[0] || null):null;
    this.setData({user:me.user || runtime.session.user(),families:me.families || [],child,ready:true,loading:false});
    if(fid && !accessible)runtime.session.clearFamily(fid);
  });},
  home(){wx.reLaunch({url:'/pages/home/home'});},
  wardrobe(){wx.reLaunch({url:'/pages/wardrobe/wardrobe'});},
  calendar(){wx.reLaunch({url:'/pages/calendar/calendar'});},
  children(){navigate('children');},
  preferences(){if(this.data.child)navigate('preferences','?id='+encodeURIComponent(this.data.child.id));},
  families(){if(!this.data.ready)return;const list=this.data.families;
    if(list.length===1)return navigate('family-detail','?id='+encodeURIComponent(list[0].id));
    navigate('families');},
  async logout(){if(await confirmation('退出登录','将清除这台设备保存的账号记录，云端孩子资料会保留。')){
    getRuntime().session.logout();wx.reLaunch({url:'/pages/login/login'});
  }}
}));

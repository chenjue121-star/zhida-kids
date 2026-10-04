const {getRuntime}=require('../../services/runtime');
const {definePage,navigate,requireLogin,selectFamily,selectChild,membership}=require('../../services/page');
const {ageLabel}=require('../../services/forms');
Page(definePage({
  data:{children:[],family:null,role:null,currentChildId:null,hasCache:false},
  onShow() {
    this._visible=true;this.setData({busy:false});
    if(!requireLogin())return;
    this.familyId=getRuntime().session.read('_','family');
    if(!this.familyId)return navigate('families','',true);
    selectFamily(this.familyId);
    const cache=getRuntime().session.read(this.familyId,'children');
    this.setData({children:cache || [],family:null,currentChildId:null,hasCache:!!cache,cached:!!cache,role:null,ready:false});
    this.reload();
  },
  reload() {
    return this.run(async valid=>{
      const {api,session}=getRuntime(); const path='/families/'+encodeURIComponent(this.familyId);
      const family=await api.request(path);const info=await membership(this.familyId);
      const children=await api.request(path+'/children');
      if(!valid())return;
      let id=session.read(this.familyId,'child');
      if(!children.some(c=>c.id===id))id=children.length?children[0].id:null;
      const list=children.map(c=>({...c,initial:c.nickname.slice(0,1),ageLabel:ageLabel(c),heightLabel:c.latest_measurement && c.latest_measurement.height_cm!=null ? c.latest_measurement.height_cm+' cm':'未知',
        weightLabel:c.latest_measurement && c.latest_measurement.weight_kg!=null ? c.latest_measurement.weight_kg+' kg':'未知'}));
      session.write(this.familyId,'children',list);
      this.setData({family,children:list,currentChildId:id,role:info.role,ready:true,cached:false,loading:false});
      selectChild(id);
    });
  },
  choose(e) { if(!this.data.ready)return;selectChild(e.currentTarget.dataset.id);this.setData({currentChildId:e.currentTarget.dataset.id}); },
  add() { if(this.data.ready && ['admin','editor'].includes(this.data.role))navigate('child-edit'); },
  edit(e) { if(!this.data.ready)return;selectChild(e.currentTarget.dataset.id);navigate('child-edit','?id='+encodeURIComponent(e.currentTarget.dataset.id)); },
  preferences(e) { if(!this.data.ready)return;selectChild(e.currentTarget.dataset.id);navigate('preferences','?id='+encodeURIComponent(e.currentTarget.dataset.id)); },
  familyDetail() { if(this.data.ready)navigate('family-detail','?id='+encodeURIComponent(this.familyId)); },
  goHome(){wx.reLaunch({url:'/pages/home/home'});}
}));

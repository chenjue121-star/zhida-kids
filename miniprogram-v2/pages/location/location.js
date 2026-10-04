const {getRuntime}=require('../../services/runtime');
const {definePage}=require('../../services/page');

Page(definePage({
  data:{city:'',selectedCity:'',selectedRegion:'',suggestions:[],message:''},
  onShow(){this._visible=true;if(!getRuntime().session.token())wx.reLaunch({url:'/pages/onboarding/onboarding'});},
  inputCity(e){this.setData({city:e.detail.value,selectedCity:'',selectedRegion:'',suggestions:[],message:'',error:''});},
  search(){
    const city=this.data.city.trim();if(!city)return this.setData({error:'请输入城市名称'});
    this.setData({selectedCity:'',selectedRegion:''});
    return this.run(async valid=>{
      const list=await getRuntime().api.request('/location/search?city='+encodeURIComponent(city));
      if(valid())this.setData({suggestions:list,message:list.length?'':'没有找到该城市，可直接使用输入的城市'});
    });
  },
  choose(e){const city=e.currentTarget.dataset.city;const region=e.currentTarget.dataset.region || '';
    if(city)this.setData({city,selectedCity:city,selectedRegion:region,error:''});},
  confirmCity(){if(this.data.loading || this.data.busy)return;
    const city=(this.data.selectedCity || this.data.city).trim();if(!city)return this.setData({error:'请输入城市名称'});
    this.save(city);},
  save(city){getRuntime().session.write('_','location',{mode:'manual',city});wx.navigateBack({delta:1});},
  auto(){getRuntime().session.remove('_','location');wx.navigateBack({delta:1});}
}));

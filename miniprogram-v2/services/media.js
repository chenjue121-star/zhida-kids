const config=require('../config');
function createMedia(platform,api,session,context){
 const downloadCache=new Map(),inFlight=new Map();
 const call=(name,options)=>new Promise((resolve,reject)=>platform[name]({...options,success:resolve,fail:reject}));
 function guard(f,edit){const generation=session.generation(),ticket=context.capture(),epoch=session.capability(f).epoch;return ()=>generation===session.generation() && context.isCurrent(ticket) && (!edit || epoch===session.capability(f).epoch && session.canEdit(f));}
 function assertCurrent(current){if(!current())throw Object.assign(new Error('账号或家庭权限已变化'),{code:'STALE'});}
 return {
  async choose(f,source){
   if(!session.canEdit(f))throw Object.assign(new Error('当前仅可查看'),{code:'EDIT_ACCESS_REVOKED',familyId:f});
   const current=guard(f,true);const result=await call('chooseMedia',{count:source==='camera'?1:9,mediaType:['image'],sourceType:[source],sizeType:['compressed']});assertCurrent(current);
   const photos=[];
   for(const file of result.tempFiles || []){
    assertCurrent(current);let localPath=file.tempFilePath,saved=false;
    try{const savedFile=await call('saveFile',{tempFilePath:localPath});localPath=savedFile.savedFilePath;saved=true;if(!current()){platform.removeSavedFile({filePath:localPath,fail(){}});assertCurrent(current);}const files=session.read(f,'media-files')||[];session.write(f,'media-files',[...new Set([...files,localPath])]);}catch(e){if(e.code==='STALE')throw e;}
    assertCurrent(current);photos.push({client_id:Date.now().toString(36)+'-'+Math.random().toString(36).slice(2),local_path:localPath,local_saved:saved,source,status:'local',error:saved?'':'照片尚未持久保存，退出可能丢失。'});
   }
   return photos;
  },
  async upload(f,b,itemId,path){
   const current=guard(f,true);assertCurrent(current);
   const fs=platform.getFileSystemManager();const data=await new Promise((resolve,reject)=>fs.readFile({filePath:path,success:r=>resolve(r.data),fail:reject}));assertCurrent(current);
   if(data.byteLength>12*1024*1024)throw new Error('照片超过 12 MB，请选择较小的图片');
   const magic=new Uint8Array(data),mime=magic[0]===137 && magic[1]===80?'image/png':magic[0]===82 && magic[1]===73?'image/webp':'image/jpeg';
   return api.request('/families/'+encodeURIComponent(f)+'/intake/batches/'+encodeURIComponent(b)+'/items/'+encodeURIComponent(itemId)+'/upload',{method:'PUT',data,headers:{'Content-Type':mime},timeout:45000,editScope:true});
  },
  async image(f,assetId,{draft=false,thumbnail=false}={}){
   if(!assetId)return '';
   const current=guard(f,draft);assertCurrent(current);
   const kind=thumbnail?'thumbnail':'content',key=session.generation()+':'+session.user().id+':'+f+':'+session.capability(f).epoch+':'+assetId+':'+kind;
   const flightKey=key+':'+context.capture().epoch+':'+(draft?'draft':'view');
   if(downloadCache.has(key)){assertCurrent(current);return downloadCache.get(key);}
   let pending=inFlight.get(flightKey);
   if(!pending){
    pending=(async()=>{
     const result=await call('downloadFile',{url:config.apiBase+'/families/'+encodeURIComponent(f)+'/assets/'+encodeURIComponent(assetId)+'/'+kind,header:{Authorization:'Bearer '+session.token()},timeout:30000});
     if(!current()){try{platform.getFileSystemManager().unlink({filePath:result.tempFilePath,fail(){}});}catch(e){}assertCurrent(current);}
     if(result.statusCode!==200){
      if(result.statusCode===403 && draft){session.capability(f,'viewer');throw Object.assign(new Error('编辑权限已变化'),{code:'EDIT_ACCESS_REVOKED',familyId:f});}
      if(result.statusCode===404){
       const members=await api.request('/families/'+encodeURIComponent(f)+'/members');assertCurrent(current);
       const own=members.find(m=>m.user_id===session.user().id && m.status==='active');
       if(draft && (!own || !['admin','editor'].includes(own.role))){session.capability(f,own?own.role:null);throw Object.assign(new Error('编辑权限已变化，草稿暂不可查看'),{code:'EDIT_ACCESS_REVOKED',familyId:f});}
      }
      throw new Error('原图暂时无法加载，请重试');
     }
     const files=session.read(f,'media-tempfiles')||[];session.write(f,'media-tempfiles',[...new Set([...files,result.tempFilePath])]);downloadCache.set(key,result.tempFilePath);return result.tempFilePath;
    })();
    inFlight.set(flightKey,pending);
   }
   try{const filePath=await pending;assertCurrent(current);return filePath;}
   finally{if(inFlight.get(flightKey)===pending)inFlight.delete(flightKey);}
  },
  async preview(f,assetId,options){const path=await this.image(f,assetId,options);if(path)platform.previewImage({current:path,urls:[path]});}
 };
}
module.exports={createMedia};

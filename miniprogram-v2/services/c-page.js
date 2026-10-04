function stale(){return Object.assign(new Error('账号、家庭权限或当前搭配已变化'),{code:'STALE'});}
function assertOutfitEdit(session,familyId){
 if(!session.canEdit(familyId))throw Object.assign(new Error('当前仅可查看，不能调整或选定搭配。'),{code:'EDIT_ACCESS_REVOKED',familyId});
}
// Capture on every new request, including result queries after a role change.
function captureOutfitAccess(runtime,familyId,{edit=false,navigation=true}={}){
 const {session,context}=runtime,generation=session.generation(),user=session.user(),access=session.capability(familyId).epoch;
 const ticket=context && context.capture();
 if(edit)assertOutfitEdit(session,familyId);
 const valid=()=>!!user && generation===session.generation() && !!session.user() && user.id===session.user().id &&
  access===session.capability(familyId).epoch && (!edit || session.canEdit(familyId)) &&
  (!navigation || !context || context.isCurrent(ticket));
 valid.assert=()=>{if(!valid())throw stale();};
 return valid;
}
module.exports={captureOutfitAccess,assertOutfitEdit,stale};

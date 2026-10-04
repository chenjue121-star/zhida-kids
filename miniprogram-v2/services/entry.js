async function resolveEntry({session,api,context}) {
  if(session.pending())return session.token()?'invitation':'login';
  if(!session.token())return 'onboarding';
  const me=await api.request('/me');
  const families=me.families || [];
  session.write('_','families',families);
  if(!families.length)return 'onboarding';
  const preferred=session.read('_','family');
  let family=families.find(item=>item.id===preferred) || families[0];
  let children=await api.request('/families/'+encodeURIComponent(family.id)+'/children');
  if(!preferred && !children.length) {
    for(const candidate of families.slice(1)) {
      const list=await api.request('/families/'+encodeURIComponent(candidate.id)+'/children');
      if(list.length){family=candidate;children=list;break;}
    }
  }
  session.write('_','family',family.id);
  session.write(family.id,'children',children);
  const previous=session.read(family.id,'child');
  const child=children.find(item=>item.id===previous) || children[0];
  context.select({familyId:family.id,childId:child?child.id:null});
  if(child)session.write(family.id,'child',child.id);
  else session.remove && session.remove(family.id,'child');
  return 'home';
}
module.exports={resolveEntry};

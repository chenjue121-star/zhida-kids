const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'); const path=require('node:path');
const root=path.resolve(__dirname,'..');
test('all native pages have registered files and real handlers',()=>{
 const app=JSON.parse(fs.readFileSync(path.join(root,'app.json')));
 assert.ok(app.pages.length>=11);
 assert.equal(app.pages[0],'pages/onboarding/onboarding');
 for(const p of app.pages){
  for(const ext of ['js','json','wxml','wxss']) assert.ok(fs.existsSync(path.join(root,p+'.'+ext)),p+'.'+ext);
  let definition; global.Page=d=>definition=d; delete require.cache[require.resolve(path.join(root,p+'.js'))]; require(path.join(root,p+'.js'));
  const markup=fs.readFileSync(path.join(root,p+'.wxml'),'utf8');
  for(const match of markup.matchAll(/(?:bind|catch)(?::?[a-z]+)="([a-zA-Z]\w*)"/g)) assert.equal(typeof definition[match[1]],'function',p+' '+match[1]);
  delete global.Page;
 }
});
test('invitation page does not accept during load or preview',async()=>{
 let page;global.Page=d=>page=d;delete require.cache[require.resolve('../pages/invitation/invitation')];require('../pages/invitation/invitation');delete global.Page;
 assert.ok(page);
 assert.ok(!page.onLoad.toString().includes('/accept'));
 assert.ok(!page.reload.toString().includes('/accept'));
 assert.ok(page.accept.toString().includes('/invitations/accept'));
});
test('member preview uses read-only text and stays separate from editable profile controls',()=>{
 const markup=fs.readFileSync(path.join(root,'pages/preferences/preferences.wxml'),'utf8');
 const start=markup.indexOf('previewMemberId');assert.ok(start>=0);
 const end=markup.indexOf('</form>',start);const preview=markup.slice(start,markup.indexOf('<view class="section">',start));
 assert.ok(end>start);assert.match(preview,/memberPreview/);assert.match(preview,/previewStyles/);assert.match(preview,/只读/);
 assert.doesNotMatch(preview,/<(?:button|checkbox|input|picker)\b/);
});
test('Phase A child identity uses monograms and has no photo upload UI',()=>{
 for(const page of ['home','children','child-edit','preferences']){
  const markup=fs.readFileSync(path.join(root,'pages',page,page+'.wxml'),'utf8');
  assert.doesNotMatch(markup,/child-avatar\.png|更换照片|上传照片/,page);
 }
});
test('cached child records are not visible before membership is verified',()=>{
 const text=fs.readFileSync(path.join(root,'pages/children/children.wxml'),'utf8');
 assert.match(text,/wx:if="\{\{ready\}\}"[\s\S]*wx:for="\{\{children\}\}"/);
});
test('primary action has readable white text and child edit target is at least 44px',()=>{
 const css=fs.readFileSync(path.join(root,'app.wxss'),'utf8');
 const color=css.match(/button\.primary\s*\{[^}]*background:\s*(#[0-9a-f]{6})/i)[1];
 const luminance=hex=>{const values=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
  return 0.2126*values[0]+0.7152*values[1]+0.0722*values[2];};
 assert.ok(1.05/(luminance(color)+0.05)>=4.5);
 const home=fs.readFileSync(path.join(root,'pages/home/home.wxss'),'utf8');
 assert.match(home,/\.sheet-edit\s*\{[^}]*min-height:44px/);
});
test('approved Phase A family and child pages use compact progressive disclosure',()=>{
 const child=fs.readFileSync(path.join(root,'pages/child-edit/child-edit.wxml'),'utf8');
 const family=fs.readFileSync(path.join(root,'pages/family-detail/family-detail.wxml'),'utf8');
 assert.doesNotMatch(child,/<view class="header">/);
 assert.match(child,/child-editor-age/);
 assert.match(child,/wx:if="\{\{measurementOpen && role !== 'viewer'\}\}"/);
 assert.doesNotMatch(family,/<view class="header">/);
 assert.match(family,/wx:if="\{\{profileOpen\}\}"/);
 assert.match(family,/memberOpenId === item\.id/);
});
test('empty wardrobe presents the two approved image-entry paths without filters',()=>{
 const wardrobe=fs.readFileSync(path.join(root,'pages/wardrobe/wardrobe.wxml'),'utf8');
 assert.match(wardrobe,/wx:if="\{\{!emptyCloset\}\}"[\s\S]*b-categories/);
 assert.match(wardrobe,/data-method="camera" bindtap="begin"/);
 assert.match(wardrobe,/data-method="album" bindtap="begin"/);
 assert.match(wardrobe,/item\.draftTitle/);
 assert.match(wardrobe,/src="\/assets\/welcome-clothes\.png"/);
 assert.doesNotMatch(wardrobe,/待确认 · \{\{pendingCandidates\}\} 件候选/);
 assert.match(wardrobe,/class="b-draft" bindtap="openDrafts"[^\n]*<button catchtap="openDrafts"/);
});
test('home empty state does not show outfit warnings or unavailable action bar',()=>{
 const home=fs.readFileSync(path.join(root,'pages/home/home.wxml'),'utf8');
 assert.match(home,/wx:if="\{\{draft && draft\.main_items\.length\}\}" class="outfit-notes"/);
 assert.match(home,/wx:if="\{\{!dailyLoading && \(!draft \|\| !draft\.main_items\.length\)\}\}" class="c-empty"/);
 assert.match(home,/wx:if="\{\{writable && contextReady && draft && draft\.main_items\.length\}\}" class="c-footer c-home-footer"/);
});

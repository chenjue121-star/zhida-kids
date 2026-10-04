const {test}=require('node:test');
const assert=require('node:assert/strict');
const {measurement,childPayload,ageLabel,ageMonths,styles,settingsPayload}=require('../services/forms');
test('blank measurements remain null, not zero; partial measurement is valid',()=>{
 assert.equal(measurement({height_cm:'',weight_kg:'',measured_on:''}),null);
 assert.deepEqual(measurement({height_cm:'92.5',weight_kg:'',measured_on:'2026-01-01'}),{height_cm:92.5,weight_kg:null,measured_on:'2026-01-01'});
});
test('reject nonfinite, zero, negative and missing measurement date',()=>{
 for(const value of ['0','-1','Infinity','abc']) assert.throws(()=>measurement({height_cm:value,weight_kg:'',measured_on:'2026-01-01'}));
 assert.throws(()=>measurement({height_cm:'90',weight_kg:'',measured_on:''}));
});
test('minimum child has no fabricated photo, measurements, skin or styles',()=>{
 const result=childPayload({nickname:' A ',birthday:'2024-01-01',height_cm:'',weight_kg:'',skin_tone:''},[]);
 assert.equal(result.nickname,'A'); assert.equal(result.measurement,null); assert.equal(result.skin_tone,null);
 assert.deepEqual(result.preferences.styles,[]); assert.equal('photo_url' in result,false);
 assert.equal(styles.length,4);
});
test('settings only retain designated member for designated mode',()=>{
 assert.equal(settingsPayload({mode:'family',designated_member_id:'1',thermal_preference:'unknown',fit_preference:'unknown',avoid_high_neck:null,version:3}).designated_member_id,null);
 assert.throws(()=>settingsPayload({mode:'designated_member',designated_member_id:null}));
});
test('age-only first child does not invent a birthday',()=>{
 const result=childPayload({nickname:'',age_years:'2',age_extra_months:'3',height_cm:'',weight_kg:'',skin_tone:''},[]);
 assert.equal(result.nickname,'宝贝');assert.equal(result.age_months,27);assert.equal(result.birthday,undefined);
 assert.equal(ageLabel({age_months:27,age_recorded_on:'2026-09-01'},new Date('2026-09-22')),'2岁3个月');
 assert.equal(ageMonths('0','0'),0);
 assert.throws(()=>ageMonths('6','12'));
 assert.throws(()=>ageMonths('7','0'));
});

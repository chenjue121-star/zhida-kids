const styles = [
  { key: 'clean_daily', label: '简洁日常' },
  { key: 'sporty', label: '运动活力' },
  { key: 'soft_natural', label: '自然柔和' },
  { key: 'playful_print', label: '童趣印花' }
];
const defaultSettings = { mode: 'family', designated_member_id: null, thermal_preference: 'unknown',
  fit_preference: 'unknown', avoid_high_neck: null };
function measurement(form) {
  const number = value => {
    if (value === '' || value === null || value === undefined) return null;
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) throw new Error('身高和体重须为大于零的数字');
    return n;
  };
  const height_cm = number(form.height_cm), weight_kg = number(form.weight_kg);
  if (height_cm === null && weight_kg === null) return null;
  if (!form.measured_on) throw new Error('请选择测量日期');
  return { height_cm, weight_kg, measured_on: form.measured_on };
}
function childPayload(form, selectedStyles) {
  const nickname = (form.nickname || '').trim() || '宝贝';
  const age = form.birthday ? {birthday:form.birthday} :
    {age_months:ageMonths(form.age_years,form.age_extra_months)};
  return { nickname, ...age, skin_tone: form.skin_tone || null,
    measurement: measurement(form), preferences: { ...defaultSettings, styles: selectedStyles } };
}
function ageMonths(years,months) {
  if (years === '' || years === undefined || months === '' || months === undefined) throw new Error('请选择孩子年龄');
  const y=Number(years),m=Number(months);
  if (!Number.isInteger(y) || !Number.isInteger(m) || y<0 || y>6 || m<0 || m>11 || y*12+m>83)
    throw new Error('请选择 0 至 6 岁的年龄');
  return y*12+m;
}
function ageLabel(child, today=new Date()) {
  const months=ageValue(child,today);
  if(months===null)return '年龄未知';
  return Math.floor(months/12)+'岁'+months%12+'个月';
}
function ageValue(child,today=new Date()) {
  let months;
  if (child.birthday) {
    const birth=new Date(child.birthday+'T00:00:00');
    if(Number.isNaN(birth.getTime()))return null;
    months=(today.getFullYear()-birth.getFullYear())*12+today.getMonth()-birth.getMonth()-(today.getDate()<birth.getDate()?1:0);
  } else if (child.age_months!==null && child.age_months!==undefined && child.age_recorded_on) {
    const recorded=new Date(child.age_recorded_on+'T00:00:00');
    if(Number.isNaN(recorded.getTime()))return null;
    months=child.age_months+(today.getFullYear()-recorded.getFullYear())*12+today.getMonth()-recorded.getMonth()-(today.getDate()<recorded.getDate()?1:0);
  } else return null;
  return Math.max(0,months);
}
function settingsPayload(form) {
  if (form.mode === 'designated_member' && !form.designated_member_id) throw new Error('请选择一位有效家庭成员');
  return { mode: form.mode, designated_member_id: form.mode === 'designated_member' ? form.designated_member_id : null,
    thermal_preference: form.thermal_preference, fit_preference: form.fit_preference,
    avoid_high_neck: form.avoid_high_neck, expected_version: form.version };
}
module.exports = { styles, defaultSettings, measurement, childPayload, ageMonths, ageLabel, ageValue, settingsPayload };

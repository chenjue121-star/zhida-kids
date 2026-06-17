function toCamelUser(user) {
  if (!user) return null
  return {
    id: user.id,
    nickname: user.nickname || user.nickName || '智搭用户',
    avatar: user.avatar || '',
    role: user.role || '',
    city: user.city || '',
    stylePreference: user.style_preference || user.stylePreference || [],
    createdAt: user.created_at || user.createdAt || ''
  }
}

function toSnakeUserProfile(user) {
  return {
    role: user.role || '',
    city: user.city || '',
    style_preference: user.stylePreference || []
  }
}

function toCamelChild(child) {
  if (!child) return null
  return {
    id: child.id,
    nickname: child.nickname,
    gender: child.gender,
    birthday: child.birthday,
    height: child.height,
    weight: child.weight || 0,
    skinTone: child.skin_tone || child.skinTone || '',
    photoUrl: child.photo_url || child.photoUrl || '',
    avatarUrl: child.avatar_url || child.avatarUrl || '',
    createdAt: child.created_at || child.createdAt || ''
  }
}

function toSnakeChild(child) {
  return {
    nickname: child.nickname,
    gender: child.gender,
    birthday: child.birthday,
    height: Number(child.height) || 0,
    weight: child.weight === '' || child.weight === undefined ? null : Number(child.weight),
    skin_tone: child.skinTone || '',
    photo_url: child.photoUrl || '',
    avatar_url: child.avatarUrl || ''
  }
}

function toCamelClothing(item) {
  if (!item) return null
  return {
    id: item.id,
    childId: item.child_id || item.childId,
    photoUrl: item.photo_url || item.photoUrl || '',
    type: item.type,
    subType: item.sub_type || item.subType || '',
    mainColor: item.main_color || item.mainColor || '',
    pattern: item.pattern || 'solid',
    season: item.season || [],
    thickness: item.thickness || '',
    styleTags: item.style_tags || item.styleTags || [],
    brand: item.brand || '',
    size: item.size || '',
    status: item.status || 'active',
    wearCount: item.wear_count || item.wearCount || 0,
    lastWornAt: item.last_worn_at || item.lastWornAt || null,
    createdAt: item.created_at || item.createdAt || ''
  }
}

function toSnakeClothing(item) {
  return {
    child_id: item.childId,
    photo_url: item.photoUrl || '',
    type: item.type,
    sub_type: item.subType || '',
    main_color: item.mainColor,
    pattern: item.pattern || 'solid',
    season: item.season || [],
    thickness: item.thickness,
    style_tags: item.styleTags || [],
    brand: item.brand || '',
    size: item.size || '',
    status: item.status || 'active'
  }
}

function toCamelDiary(item) {
  if (!item) return null
  return {
    id: item.id,
    childId: item.child_id || item.childId,
    date: item.date,
    clothingIds: item.clothing_ids || item.clothingIds || [],
    scene: item.scene || '',
    reason: item.reason || '',
    note: item.note || '',
    mood: item.mood || '',
    rating: item.rating || 0,
    actualPhotoUrl: item.actual_photo_url || item.actualPhotoUrl || '',
    createdAt: item.created_at || item.createdAt || ''
  }
}

function toSnakeDiary(item) {
  return {
    child_id: item.childId,
    date: item.date,
    clothing_ids: item.clothingIds || [],
    scene: item.scene || '',
    reason: item.reason || '',
    note: item.note || '',
    mood: item.mood || '',
    rating: item.rating || 0,
    actual_photo_url: item.actualPhotoUrl || ''
  }
}

module.exports = {
  toCamelUser,
  toSnakeUserProfile,
  toCamelChild,
  toSnakeChild,
  toCamelClothing,
  toSnakeClothing,
  toCamelDiary,
  toSnakeDiary
}

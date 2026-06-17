const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const Theme = require('../../utils/theme')
const { toCamelClothing, toSnakeDiary } = require('../../utils/model')
const { SCENES, CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, SEASONS, THICKNESS } = require('../../utils/constant')
const { getWeather, getThicknessRecommendation } = require('../../utils/weather')

Page({
  data: {
    greetingText: '你好呀',
    todayText: '加载中...',
    weatherEmoji: '☀️',
    weatherInfo: { city: '加载中', temp: '--', weather: '晴', suggestion: '正在获取天气...' },
    children: [],
    childTabs: [],
    currentChildIndex: 0,
    currentChild: null,
    childAgeText: '',
    clothingCount: 0,
    scenes: SCENES,
    displayScenes: [
      { value: 'home', scene: 'home', label: '日常', icon: '🏠' },
      { value: 'school', scene: 'school', label: '上学', icon: '🏫' },
      { value: 'outdoor', scene: 'outdoor', label: '户外', icon: '⛳' },
      { value: 'sport', scene: 'outdoor', label: '运动', icon: '⚽' },
      { value: 'party', scene: 'party', label: '聚会', icon: '🎉' },
      { value: 'travel', scene: 'travel', label: '出游', icon: '📸' }
    ],
    selectedSceneTab: 'home',
    selectedScene: 'home',
    sceneEmoji: '🏠',
    selectedSceneLabel: '日常',
    loading: false,
    outfit: null,
    heroItems: [],
    clothingList: [],
    replacementVisible: false,
    replacementGroup: '',
    replacementGroupLabel: '',
    replacementCandidates: [],
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key,
  },

  onLoad() {},

  onShow() {
    const app = getApp()
    this.setData({
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key
    })
    Theme.applyAllTheme(app.globalData.theme)
    this.loadData()
  },

  async loadData() {
    const app = getApp()
    await app.ensureReady()
    const children = Storage.getChildren()
    let currentChildIndex = app.globalData.currentChildIndex || 0
    if (currentChildIndex >= children.length) currentChildIndex = 0
    const currentChild = children[currentChildIndex] || null

    // Check login and onboarding
    if (!app.globalData.isLoggedIn) {
      wx.navigateTo({ url: '/pages/login/login' })
      return
    }
    if (!wx.getStorageSync('onboardingComplete')) {
      wx.navigateTo({ url: '/pages/onboarding/onboarding' })
      return
    }

    let clothingCount = 0
    let clothingList = []
    if (currentChild) {
      try {
        clothingList = (await api.get('/clothing', { child_id: currentChild.id })).map(toCamelClothing)
          .map(item => this.enrichClothing(item))
        clothingCount = clothingList.length
      } catch (e) {
        clothingList = []
        clothingCount = 0
      }
    }

    this.setData({
      children,
      childTabs: this.buildChildTabs(children),
      currentChildIndex,
      currentChild,
      childAgeText: this.getAgeText(currentChild),
      clothingCount,
      clothingList
    })

    // Load weather
    try {
      const weatherInfo = await getWeather()
      this.setData({
        weatherInfo,
        greetingText: this.getGreetingText(),
        todayText: this.getTodayText(),
        weatherEmoji: this.getWeatherEmoji(weatherInfo.weather)
      })
    } catch (e) {
      const fallback = { city: '未知', temp: 25, weather: '晴', suggestion: '适宜出行' }
      this.setData({
        weatherInfo: fallback,
        greetingText: this.getGreetingText(),
        todayText: this.getTodayText(),
        weatherEmoji: '☀️'
      })
    }

    // Auto generate outfit
    if (currentChild && clothingCount >= 3) {
      this.generateOutfit()
    }
  },

  async switchChild(e) {
    const index = e.currentTarget.dataset.index
    if (index >= this.data.children.length) return
    const app = getApp()
    app.switchChild(index)
    this.setData({
      currentChildIndex: index,
      currentChild: this.data.children[index],
      childAgeText: this.getAgeText(this.data.children[index]),
      outfit: null
    })
    try {
      const clothingList = (await api.get('/clothing', { child_id: this.data.children[index].id }))
        .map(toCamelClothing)
        .map(item => this.enrichClothing(item))
      const clothingCount = clothingList.length
      this.setData({ clothingCount, clothingList })
      if (clothingCount >= 3) {
        this.generateOutfit()
      }
    } catch (e) {
      this.setData({ clothingCount: 0, clothingList: [] })
    }
  },

  selectScene(e) {
    const tabValue = e.currentTarget.dataset.value
    const displayScene = this.data.displayScenes.find(item => item.value === tabValue)
    const sceneInfo = SCENES.find(s => s.value === (displayScene ? displayScene.scene : tabValue))
    this.setData({
      selectedSceneTab: tabValue,
      selectedScene: displayScene ? displayScene.scene : tabValue,
      sceneEmoji: (displayScene && displayScene.icon) || (sceneInfo && sceneInfo.icon) || '🏠',
      selectedSceneLabel: (displayScene && displayScene.label) || (sceneInfo && sceneInfo.label) || ''
    })
    this.generateOutfit()
  },

  async generateOutfit(excludeIds = []) {
    const { currentChild, weatherInfo, selectedScene } = this.data
    if (!currentChild) return

    this.setData({ loading: true })

    try {
      const res = await api.post('/outfits/recommend', {
        child_id: currentChild.id,
        scene: selectedScene,
        weather: weatherInfo,
        exclude_clothing_ids: excludeIds
      })
      const outfit = this.normalizeOutfit(res)
      this.setData({
        loading: false,
        outfit,
        heroItems: this.buildHeroItems(outfit)
      })
    } catch (e) {
      const clothing = this.data.clothingList.filter(c => c.status === 'active')
      const outfit = this.localMatch(clothing, weatherInfo, selectedScene)
      this.setData({
        loading: false,
        outfit,
        heroItems: this.buildHeroItems(outfit)
      })
    }
  },

  normalizeOutfit(res) {
    const items = (res.items || []).map(toCamelClothing).map(item => this.enrichClothing(item))
    return {
      items,
      reason: res.reason || '',
      tips: res.tips || '',
      warnings: res.warnings || [],
      scene: res.scene || this.data.selectedScene,
      date: res.date || new Date().toISOString().split('T')[0],
      weather: res.weather || this.data.weatherInfo,
      source: res.source || 'fallback',
      styleProfile: res.style_profile || res.styleProfile || '',
      rulesetId: res.ruleset_id || '',
      rulesetVersion: res.ruleset_version || ''
    }
  },

  buildChildTabs(children) {
    return children.map(child => ({
      ...child,
      ageText: this.getAgeText(child),
      avatarText: child.gender === 'boy' ? '👦' : '👧'
    }))
  },

  getAgeText(child) {
    if (!child || !child.birthday) return ''
    const birthday = new Date(child.birthday)
    if (Number.isNaN(birthday.getTime())) return ''
    const now = new Date()
    let years = now.getFullYear() - birthday.getFullYear()
    let months = now.getMonth() - birthday.getMonth()
    if (now.getDate() < birthday.getDate()) months -= 1
    if (months < 0) {
      years -= 1
      months += 12
    }
    if (years <= 0) return `${months}个月`
    return `${years}岁${months}个月`
  },

  buildHeroItems(outfit) {
    if (!outfit || !outfit.items) return []
    const groups = [
      { key: 'top', label: '上衣', types: ['top', 'innerwear', 'babywear'], iconEmoji: '👕' },
      { key: 'bottom', label: '下装', types: ['pants', 'skirt', 'set'], iconEmoji: '👖' },
      { key: 'shoes', label: '鞋子', types: ['shoes'], iconEmoji: '👟' },
      { key: 'accessory', label: '配饰', types: ['hat', 'accessory', 'outerwear', 'sleepwear'], iconEmoji: '🧢' }
    ]
    return groups.map(group => {
      const item = outfit.items.find(i => group.types.includes(i.type))
      if (!item) return null
      return {
        ...item,
        groupKey: group.key,
        groupLabel: group.label,
        iconEmoji: group.iconEmoji,
        displayName: `${item.colorLabel || ''}${item.subTypeLabel ? item.subTypeLabel : item.typeLabel || ''}`
      }
    }).filter(Boolean)
  },

  enrichClothing(item) {
    const typeInfo = CLOTHING_TYPES.find(t => t.value === item.type)
    const subTypes = CLOTHING_SUB_TYPES[item.type] || []
    const subTypeInfo = subTypes.find(s => s.value === item.subType)
    const colorInfo = COLORS.find(c => c.value === item.mainColor)
    const seasonLabel = (item.season || []).map(value => {
      const season = SEASONS.find(s => s.value === value)
      return season ? season.label : value
    }).join('/')
    const thicknessInfo = THICKNESS.find(t => t.value === item.thickness)
    return {
      ...item,
      typeLabel: typeInfo ? typeInfo.label : item.type,
      subTypeLabel: subTypeInfo ? subTypeInfo.label : '',
      colorLabel: colorInfo ? colorInfo.label : '',
      seasonLabel,
      thicknessLabel: thicknessInfo ? thicknessInfo.label : item.thickness,
      displayName: `${colorInfo ? colorInfo.label : ''}${subTypeInfo ? subTypeInfo.label : (typeInfo ? typeInfo.label : '')}`
    }
  },

  localMatch(clothing, weather, scene) {
    const recommended = getThicknessRecommendation(weather.temp)

    const findBest = (type) => {
      const candidates = clothing.filter(c => c.type === type)
      if (candidates.length === 0) return null

      // Prefer matching thickness
      const thicknessMatch = candidates.filter(c => c.thickness === recommended)
      const pick = thicknessMatch.length > 0
        ? thicknessMatch[Math.floor(Math.random() * thicknessMatch.length)]
        : candidates[Math.floor(Math.random() * candidates.length)]

      const typeInfo = CLOTHING_TYPES.find(t => t.value === pick.type)
      const subTypes = CLOTHING_SUB_TYPES[pick.type] || []
      const subTypeInfo = subTypes.find(s => s.value === pick.subType)
      const colorInfo = COLORS.find(c => c.value === pick.mainColor)

      return {
        ...pick,
        typeLabel: typeInfo ? typeInfo.label : pick.type,
        subTypeLabel: subTypeInfo ? subTypeInfo.label : '',
        colorLabel: colorInfo ? colorInfo.label : ''
      }
    }

    const top = findBest('top')
    const bottom = findBest('pants') || findBest('skirt')
    const shoes = findBest('shoes')
    const outerwear = weather.temp < 20 ? findBest('outerwear') : null
    const hat = findBest('hat')

    const items = [top, bottom, shoes, outerwear, hat].filter(Boolean)

    if (items.length === 0) {
      return null
    }

    const sceneInfo = SCENES.find(s => s.value === scene)
    const sceneName = sceneInfo ? sceneInfo.label : ''

    let reason = `今天${weather.city}${weather.temp}°C，${weather.weather}。`
    if (weather.temp >= 28) {
      reason += `天气较热，选择了薄款透气的衣物，让${this.data.currentChild.nickname}凉爽舒适。`
    } else if (weather.temp < 10) {
      reason += `天气寒冷，搭配了保暖外套，注意防寒。`
    } else {
      reason += `温度适中，搭配舒适日常穿着。`
    }
    if (sceneName) {
      reason += `适合${sceneName}场景。`
    }

    let tips = ''
    if (weather.temp >= 15 && weather.temp <= 25) {
      tips = '今天温差可能较大，建议备一件薄外套'
    }

    return {
      items,
      reason,
      tips,
      warnings: [],
      scene,
      date: new Date().toISOString().split('T')[0]
    }
  },

  refreshOutfit() {
    const excludeIds = this.data.outfit ? this.data.outfit.items.map(item => item.id) : []
    this.generateOutfit(excludeIds)
  },

  async wearThis() {
    const { outfit, currentChild } = this.data
    if (!outfit || !currentChild) return

    // Save to diary
    const diary = {
      childId: currentChild.id,
      date: outfit.date,
      clothingIds: outfit.items.map(i => i.id),
      scene: outfit.scene,
      reason: outfit.reason,
      note: '',
      mood: '',
      rating: 0
    }
    await api.post('/diaries', toSnakeDiary(diary))

    // Update wear count
    await Promise.all(outfit.items.map(item => api.post(`/clothing/${item.id}/wear`)))

    wx.showToast({ title: '已记录今日穿搭', icon: 'success' })
  },

  onItemTap(e) {
    const id = e.currentTarget.dataset.id
    const group = e.currentTarget.dataset.group
    this.openReplacement(group, id)
  },

  groupTypes(group) {
    const map = {
      top: ['top', 'innerwear', 'babywear'],
      bottom: ['pants', 'skirt', 'set'],
      shoes: ['shoes'],
      accessory: ['hat', 'accessory', 'outerwear', 'sleepwear']
    }
    return map[group] || []
  },

  openReplacement(group, currentId) {
    const labels = { top: '上衣', bottom: '下装', shoes: '鞋子', accessory: '配饰' }
    const types = this.groupTypes(group)
    const currentItemId = Number(currentId)
    const candidates = this.data.clothingList
      .filter(item => item.status === 'active' && types.includes(item.type) && Number(item.id) !== currentItemId)
    this.setData({
      replacementVisible: true,
      replacementGroup: group,
      replacementGroupLabel: labels[group] || '单品',
      replacementCandidates: candidates
    })
  },

  closeReplacement() {
    this.setData({ replacementVisible: false, replacementGroup: '', replacementGroupLabel: '', replacementCandidates: [] })
  },

  selectReplacement(e) {
    const id = Number(e.currentTarget.dataset.id)
    const replacement = this.data.clothingList.find(item => Number(item.id) === id)
    if (!replacement || !this.data.outfit) return
    const group = this.data.replacementGroup
    const types = this.groupTypes(group)
    const items = this.data.outfit.items.filter(item => !types.includes(item.type))
    items.push(replacement)
    const outfit = {
      ...this.data.outfit,
      items,
      reason: `${this.data.outfit.reason || ''} 已根据手动选择替换${this.data.replacementGroupLabel}，请确认最终搭配。`
    }
    this.setData({
      outfit,
      heroItems: this.buildHeroItems(outfit),
      replacementVisible: false,
      replacementGroup: '',
      replacementGroupLabel: '',
      replacementCandidates: []
    })
  },

  viewReplacementDetail(e) {
    const id = e.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/clothing-detail/clothing-detail?id=${id}` })
  },

  goAddChild() {
    wx.navigateTo({ url: '/pages/child-profile/child-profile' })
  },

  goAddClothing() {
    wx.navigateTo({ url: '/pages/add-clothing/add-clothing' })
  },

  getGreetingText() {
    const hour = new Date().getHours()
    if (hour < 6) return '夜深了'
    if (hour < 9) return '早安呀'
    if (hour < 12) return '上午好'
    if (hour < 14) return '中午好'
    if (hour < 18) return '下午好'
    if (hour < 22) return '晚上好'
    return '夜深了'
  },

  getTodayText() {
    const now = new Date()
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    const month = now.getMonth() + 1
    const day = now.getDate()
    const weekday = weekdays[now.getDay()]
    return `${month}月${day}日 · ${weekday}`
  },

  getWeatherEmoji(weather) {
    if (!weather) return '☀️'
    if (weather.includes('雨')) return '🌧️'
    if (weather.includes('雪')) return '❄️'
    if (weather.includes('云') || weather.includes('阴')) return '⛅'
    if (weather.includes('雾') || weather.includes('霾')) return '🌫️'
    return '☀️'
  }
})

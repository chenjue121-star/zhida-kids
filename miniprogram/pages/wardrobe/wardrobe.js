const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const Theme = require('../../utils/theme')
const { toCamelClothing } = require('../../utils/model')
const { CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, SEASONS } = require('../../utils/constant')

Page({
  data: {
    children: [],
    currentChildIndex: 0,
    clothingList: [],
    filteredList: [],
    wardrobeStats: null,
    typeFilters: CLOTHING_TYPES,
    activeFilter: 'all',
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key
  },

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
    if (!app.globalData.isLoggedIn) {
      wx.navigateTo({ url: '/pages/login/login' })
      return
    }
    const rawChildren = Storage.getChildren()
    const children = rawChildren.map(c => ({ ...c, ageText: this.calcAgeText(c) }))
    let currentChildIndex = app.globalData.currentChildIndex || 0
    if (currentChildIndex >= children.length) currentChildIndex = 0
    const currentChild = children[currentChildIndex]

    let clothingList = []
    if (currentChild) {
      try {
        clothingList = (await api.get('/clothing', { child_id: currentChild.id }))
          .map(toCamelClothing)
          .map(item => this.enrichItem(item))
      } catch (e) {
        clothingList = []
      }
    }

    this.setData({
      children,
      currentChildIndex,
      clothingList,
      filteredList: clothingList,
      wardrobeStats: this.buildStats(clothingList)
    })
  },

  calcAgeText(child) {
    if (!child || !child.birthday) return ''
    const birthday = new Date(child.birthday)
    if (Number.isNaN(birthday.getTime())) return ''
    const now = new Date()
    let years = now.getFullYear() - birthday.getFullYear()
    let months = now.getMonth() - birthday.getMonth()
    if (now.getDate() < birthday.getDate()) months -= 1
    if (months < 0) { years -= 1; months += 12 }
    if (years <= 0) return `${months}个月`
    return `${years}岁${months}个月`
  },

  buildStats(list) {
    const total = list.length
    const active = list.filter(item => item.status === 'active').length
    const stored = list.filter(item => item.status === 'stored').length
    const retired = list.filter(item => item.status === 'retired').length
    const wornTotal = list.reduce((sum, item) => sum + (Number(item.wearCount) || 0), 0)
    const typeCounts = list.reduce((acc, item) => {
      acc[item.type] = (acc[item.type] || 0) + 1
      return acc
    }, {})
    const topTypes = Object.keys(typeCounts)
      .map(type => {
        const typeInfo = CLOTHING_TYPES.find(t => t.value === type) || {}
        return {
          type,
          label: typeInfo.label || type,
          icon: typeInfo.icon || '👕',
          count: typeCounts[type],
          percent: total ? Math.round((typeCounts[type] / total) * 100) : 0
        }
      })
      .sort((a, b) => b.count - a.count)
      .slice(0, 4)
    const mostWorn = [...list]
      .sort((a, b) => (Number(b.wearCount) || 0) - (Number(a.wearCount) || 0))
      .find(item => Number(item.wearCount) > 0)
    const missingCore = ['top', 'pants', 'shoes']
      .filter(type => !typeCounts[type])
      .map(type => (CLOTHING_TYPES.find(t => t.value === type) || {}).label || type)

    return {
      total,
      active,
      stored,
      retired,
      wornTotal,
      topTypes,
      mostWornName: mostWorn ? `${mostWorn.colorLabel}${mostWorn.subTypeLabel || mostWorn.typeLabel}` : '暂无',
      missingHint: missingCore.length ? `建议补充${missingCore.join('、')}` : '核心单品已齐全'
    }
  },

  enrichItem(item) {
    const typeInfo = CLOTHING_TYPES.find(t => t.value === item.type) || {}
    const subTypes = CLOTHING_SUB_TYPES[item.type] || []
    const subTypeInfo = subTypes.find(s => s.value === item.subType) || {}
    const colorInfo = COLORS.find(c => c.value === item.mainColor) || {}
    const seasonLabels = (item.season || []).map(s => {
      const si = SEASONS.find(ss => ss.value === s)
      return si ? si.label : s
    })

    return {
      ...item,
      typeIcon: typeInfo.icon || '👕',
      typeLabel: typeInfo.label || '',
      subTypeLabel: subTypeInfo.label || '',
      colorLabel: colorInfo.label || '',
      seasonLabel: seasonLabels.join('/')
    }
  },

  switchChild(e) {
    const index = e.currentTarget.dataset.index
    getApp().switchChild(index)
    this.setData({ currentChildIndex: index, activeFilter: 'all' })
    this.loadData()
  },

  setFilter(e) {
    const value = e.currentTarget.dataset.value
    this.setData({ activeFilter: value })

    if (value === 'all') {
      this.setData({ filteredList: this.data.clothingList })
    } else {
      this.setData({
        filteredList: this.data.clothingList.filter(c => c.type === value)
      })
    }
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/clothing-detail/clothing-detail?id=${id}` })
  },

  goAdd() {
    wx.navigateTo({ url: '/pages/add-clothing/add-clothing' })
  },

  goAddChild() {
    wx.navigateTo({ url: '/pages/child-profile/child-profile' })
  }
})

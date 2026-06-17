const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const { toCamelClothing } = require('../../utils/model')
const { CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, PATTERNS, SEASONS, THICKNESS, STYLE_TAGS, CLOTHING_STATUS } = require('../../utils/constant')
const Theme = require('../../utils/theme')

Page({
  data: {
    item: null,
    typeIcon: '',
    typeLabel: '',
    subTypeLabel: '',
    colorLabel: '',
    colorHex: '',
    patternLabel: '',
    seasonLabel: '',
    thicknessLabel: '',
    styleTagLabels: [],
    statusLabel: '',
    lastWornText: '',
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key,
  },

  onLoad(options) {
    this.itemId = options.id
    const app = getApp()
    this.setData({
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key
    })
  },

  onShow() {
    this.loadItem()
  },

  async loadItem() {
    const item = toCamelClothing(await api.get(`/clothing/${this.itemId}`))
    if (!item) {
      wx.showToast({ title: '衣物不存在', icon: 'none' })
      wx.navigateBack()
      return
    }

    const typeInfo = CLOTHING_TYPES.find(t => t.value === item.type) || {}
    const subTypes = CLOTHING_SUB_TYPES[item.type] || []
    const subTypeInfo = subTypes.find(s => s.value === item.subType) || {}
    const colorInfo = COLORS.find(c => c.value === item.mainColor) || {}
    const patternInfo = PATTERNS.find(p => p.value === item.pattern) || {}
    const thicknessInfo = THICKNESS.find(t => t.value === item.thickness) || {}
    const statusInfo = CLOTHING_STATUS.find(s => s.value === item.status) || {}

    const seasonLabel = (item.season || []).map(s => {
      const si = SEASONS.find(ss => ss.value === s)
      return si ? si.label : s
    }).join('/')

    const styleTagLabels = (item.styleTags || []).map(s => {
      const si = STYLE_TAGS.find(ss => ss.value === s)
      return si ? si.label : s
    })

    let lastWornText = '未穿过'
    if (item.lastWornAt) {
      const days = Math.floor((Date.now() - new Date(item.lastWornAt).getTime()) / 86400000)
      lastWornText = days === 0 ? '今天' : `${days}天前`
    }

    this.setData({
      item,
      typeIcon: typeInfo.icon || '👕',
      typeLabel: typeInfo.label || '',
      subTypeLabel: subTypeInfo.label || '',
      colorLabel: colorInfo.label || '',
      colorHex: colorInfo.hex || '#ccc',
      patternLabel: patternInfo.label || '',
      seasonLabel,
      thicknessLabel: thicknessInfo.label || '',
      styleTagLabels,
      statusLabel: statusInfo.label || '',
      lastWornText
    })
  },

  async changeStatus(e) {
    const status = e.currentTarget.dataset.status
    await api.put(`/clothing/${this.itemId}`, { status })
    await this.loadItem()
    const statusMap = { active: '已恢复', stored: '已收纳', retired: '已淘汰' }
    wx.showToast({ title: statusMap[status] || '已更新', icon: 'success' })
  },

  editItem() {
    wx.navigateTo({ url: `/pages/add-clothing/add-clothing?mode=edit&id=${this.itemId}` })
  },

  deleteItem() {
    wx.showModal({
      title: '确认删除',
      content: '删除后无法恢复，确定要删除吗？',
      confirmColor: '#E17055',
      success: (res) => {
        if (res.confirm) {
          api.del(`/clothing/${this.itemId}`).then(() => {
          wx.showToast({ title: '已删除', icon: 'success' })
          wx.navigateBack()
          })
        }
      }
    })
  }
})

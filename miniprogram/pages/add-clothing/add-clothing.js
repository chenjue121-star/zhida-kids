const Storage = require('../../utils/storage')
const api = require('../../utils/api')
const { toCamelClothing, toSnakeClothing } = require('../../utils/model')
const { CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, COLOR_GROUPS, PATTERNS, SEASONS, THICKNESS, STYLE_TAGS } = require('../../utils/constant')
const Theme = require('../../utils/theme')

Page({
  data: {
    pageTitle: '添加衣物',
    isEdit: false,
    clothingId: '',
    photoUrl: '',
    uploading: false,
    recognizing: false,
    saving: false,
    recognitionNotes: '',
    children: [],
    selectedChildId: '',
    typeOptions: CLOTHING_TYPES,
    selectedType: '',
    subTypeOptions: [],
    selectedSubType: '',
    colorOptions: COLORS,
    colorGroups: COLOR_GROUPS,
    activeColorGroup: 'all',
    colorKeyword: '',
    filteredColors: COLORS,
    selectedColor: '',
    patternOptions: PATTERNS,
    selectedPattern: 'solid',
    seasonOptions: SEASONS.map(s => ({ ...s, selected: false })),
    selectedSeasons: {},
    thicknessOptions: THICKNESS,
    selectedThickness: '',
    styleOptions: STYLE_TAGS.map(s => ({ ...s, selected: false })),
    selectedStyleTags: {},
    brand: '',
    size: '',
    fromOnboarding: false,
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key,
  },

  async onLoad(options) {
    const app = getApp()
    await app.ensureReady()
    const children = Storage.getChildren()
    const currentChild = children[app.globalData.currentChildIndex] || children[0]
    const isEdit = options.mode === 'edit' && !!options.id

    this.setData({
      pageTitle: isEdit ? '编辑衣物' : '添加衣物',
      isEdit,
      clothingId: options.id || '',
      children,
      selectedChildId: currentChild ? currentChild.id : '',
      fromOnboarding: options.from === 'onboarding',
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key,
    })

    if (isEdit) {
      await this.loadClothing(options.id)
      return
    }

    if (options.mode === 'camera') {
      this.takePhoto()
    }
  },

  async loadClothing(id) {
    const item = toCamelClothing(await api.get(`/clothing/${id}`))
    const selectedSeasons = {}
    ;(item.season || []).forEach(value => { selectedSeasons[value] = true })
    const seasonOptions = SEASONS.map(s => ({ ...s, selected: selectedSeasons[s.value] || false }))
    const selectedStyleTags = {}
    ;(item.styleTags || []).forEach(value => { selectedStyleTags[value] = true })
    const styleOptions = STYLE_TAGS.map(s => ({ ...s, selected: selectedStyleTags[s.value] || false }))
    this.setData({
      photoUrl: item.photoUrl || '',
      selectedChildId: item.childId,
      selectedType: item.type,
      subTypeOptions: CLOTHING_SUB_TYPES[item.type] || [],
      selectedSubType: item.subType || '',
      selectedColor: item.mainColor || '',
      selectedPattern: item.pattern || 'solid',
      selectedSeasons,
      seasonOptions,
      selectedThickness: item.thickness || '',
      selectedStyleTags,
      styleOptions,
      brand: item.brand || '',
      size: item.size || ''
    })
    this.updateFilteredColors()
  },

  choosePhoto() {
    wx.showActionSheet({
      itemList: ['拍照', '从相册选择'],
      success: (res) => {
        if (res.tapIndex === 0) {
          this.takePhoto()
        } else {
          this.pickFromAlbum()
        }
      }
    })
  },

  takePhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera'],
      success: async (res) => {
        await this.handleSelectedPhoto(res.tempFiles[0].tempFilePath)
      }
    })
  },

  pickFromAlbum() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album'],
      success: async (res) => {
        await this.handleSelectedPhoto(res.tempFiles[0].tempFilePath)
      }
    })
  },

  async handleSelectedPhoto(filePath) {
    try {
      const photoUrl = await this.uploadPhoto(filePath)
      await this.recognizePhoto(photoUrl)
    } catch (err) {
      wx.showToast({ title: '图片处理失败，可手动填写', icon: 'none' })
    }
  },

  async uploadPhoto(filePath) {
    this.setData({ photoUrl: filePath, uploading: true })
    try {
      const uploaded = await api.uploadImage(filePath)
      this.setData({ photoUrl: uploaded.url })
      return uploaded.url
    } finally {
      this.setData({ uploading: false })
    }
  },

  async recognizePhoto(photoUrl) {
    this.setData({ recognizing: true })
    try {
      const result = await api.post('/clothing/recognize', { photo_url: photoUrl })
      this.applyRecognition(result)
      wx.showToast({ title: '识别完成，请确认', icon: 'none' })
    } catch (err) {
      this.setData({ recognitionNotes: 'AI识别失败，请手动填写衣物信息。' })
      wx.showToast({ title: '识别失败，可手动填写', icon: 'none' })
    } finally {
      this.setData({ recognizing: false })
    }
  },

  applyRecognition(result) {
    const type = this.validValue(result.type, CLOTHING_TYPES) ? result.type : ''
    const nextType = type || this.data.selectedType
    const subTypeOptions = CLOTHING_SUB_TYPES[nextType] || []
    const selectedSeasons = {}
    ;(result.season || []).forEach(value => {
      if (this.validValue(value, SEASONS)) selectedSeasons[value] = true
    })
    const seasonOptions = SEASONS.map(s => ({ ...s, selected: selectedSeasons[s.value] || false }))
    const selectedStyleTags = { ...this.data.selectedStyleTags }
    ;(result.style_tags || result.styleTags || []).forEach(value => {
      if (this.validValue(value, STYLE_TAGS)) selectedStyleTags[value] = true
    })
    const styleOptions = STYLE_TAGS.map(s => ({ ...s, selected: selectedStyleTags[s.value] || false }))

    this.setData({
      selectedType: nextType,
      subTypeOptions,
      selectedSubType: this.validValue(result.sub_type, subTypeOptions) ? result.sub_type : '',
      selectedColor: this.validValue(result.main_color, COLORS) ? result.main_color : this.data.selectedColor,
      selectedPattern: this.validValue(result.pattern, PATTERNS) ? result.pattern : this.data.selectedPattern,
      selectedSeasons: Object.keys(selectedSeasons).length ? selectedSeasons : this.data.selectedSeasons,
      seasonOptions: Object.keys(selectedSeasons).length ? seasonOptions : this.data.seasonOptions,
      selectedThickness: this.validValue(result.thickness, THICKNESS) ? result.thickness : this.data.selectedThickness,
      selectedStyleTags: Object.keys(selectedStyleTags).length ? selectedStyleTags : this.data.selectedStyleTags,
      styleOptions: Object.keys(selectedStyleTags).length ? styleOptions : this.data.styleOptions,
      brand: result.brand || this.data.brand,
      size: result.size || this.data.size,
      recognitionNotes: result.notes || ''
    })
    this.updateFilteredColors()
  },

  validValue(value, options) {
    return !!options.find(item => item.value === value)
  },

  selectChild(e) {
    this.setData({ selectedChildId: e.currentTarget.dataset.id })
  },

  selectType(e) {
    const value = e.currentTarget.dataset.value
    const subTypeOptions = CLOTHING_SUB_TYPES[value] || []
    this.setData({
      selectedType: value,
      subTypeOptions,
      selectedSubType: subTypeOptions.length > 0 ? subTypeOptions[0].value : ''
    })
  },

  selectSubType(e) {
    this.setData({ selectedSubType: e.currentTarget.dataset.value })
  },

  selectColor(e) {
    this.setData({ selectedColor: e.currentTarget.dataset.value })
  },

  selectColorGroup(e) {
    this.setData({ activeColorGroup: e.currentTarget.dataset.value })
    this.updateFilteredColors()
  },

  onColorSearch(e) {
    this.setData({ colorKeyword: e.detail.value || '' })
    this.updateFilteredColors()
  },

  updateFilteredColors() {
    const { activeColorGroup, colorKeyword } = this.data
    const keyword = (colorKeyword || '').trim().toLowerCase()
    const filteredColors = COLORS.filter(color => {
      const matchGroup = activeColorGroup === 'all' || color.group === activeColorGroup
      const matchKeyword = !keyword || color.label.indexOf(keyword) >= 0 || color.value.toLowerCase().indexOf(keyword) >= 0
      return matchGroup && matchKeyword
    })
    this.setData({ filteredColors })
  },

  selectPattern(e) {
    this.setData({ selectedPattern: e.currentTarget.dataset.value })
  },

  toggleSeason(e) {
    const value = e.currentTarget.dataset.value
    const selectedSeasons = { ...this.data.selectedSeasons }
    if (value === 'all') {
      if (selectedSeasons.all) {
        this.setData({
          selectedSeasons: {},
          seasonOptions: this.data.seasonOptions.map(s => ({ ...s, selected: false }))
        })
      } else {
        this.setData({
          selectedSeasons: { all: true },
          seasonOptions: this.data.seasonOptions.map(s => ({ ...s, selected: s.value === 'all' }))
        })
      }
    } else {
      delete selectedSeasons.all
      selectedSeasons[value] = !selectedSeasons[value]
      if (!selectedSeasons[value]) delete selectedSeasons[value]
      const seasonOptions = this.data.seasonOptions.map(s => ({
        ...s,
        selected: s.value === 'all' ? false : selectedSeasons[s.value] || false
      }))
      this.setData({ selectedSeasons, seasonOptions })
    }
  },

  selectThickness(e) {
    this.setData({ selectedThickness: e.currentTarget.dataset.value })
  },

  toggleStyleTag(e) {
    const value = e.currentTarget.dataset.value
    const selectedStyleTags = { ...this.data.selectedStyleTags }
    selectedStyleTags[value] = !selectedStyleTags[value]
    if (!selectedStyleTags[value]) delete selectedStyleTags[value]
    const styleOptions = this.data.styleOptions.map(s => ({
      ...s,
      selected: selectedStyleTags[s.value] || false
    }))
    this.setData({ selectedStyleTags, styleOptions })
  },

  onBrand(e) {
    this.setData({ brand: e.detail.value })
  },

  onSize(e) {
    this.setData({ size: e.detail.value })
  },

  async saveClothing() {
    if (this.data.saving) return
    const { selectedChildId, selectedType, selectedColor, selectedSeasons, selectedThickness, photoUrl } = this.data

    if (!selectedChildId) {
      wx.showToast({ title: '请选择所属宝贝', icon: 'none' })
      return
    }
    if (!selectedType) {
      wx.showToast({ title: '请选择衣物类型', icon: 'none' })
      return
    }
    if (!selectedColor) {
      wx.showToast({ title: '请选择颜色', icon: 'none' })
      return
    }
    if (Object.keys(selectedSeasons).length === 0) {
      wx.showToast({ title: '请选择适合季节', icon: 'none' })
      return
    }
    if (!selectedThickness) {
      wx.showToast({ title: '请选择厚度', icon: 'none' })
      return
    }

    const clothing = {
      childId: selectedChildId,
      photoUrl: photoUrl,
      type: selectedType,
      subType: this.data.selectedSubType,
      mainColor: selectedColor,
      pattern: this.data.selectedPattern,
      season: Object.keys(selectedSeasons),
      thickness: selectedThickness,
      styleTags: Object.keys(this.data.selectedStyleTags),
      brand: this.data.brand,
      size: this.data.size,
      status: 'active'
    }

    this.setData({ saving: true })
    try {
      if (this.data.isEdit) {
        const payload = toSnakeClothing(clothing)
        delete payload.child_id
        await api.put(`/clothing/${this.data.clothingId}`, payload)
        wx.showToast({ title: '已保存', icon: 'success' })
        wx.navigateBack()
        return
      }

      await api.post('/clothing', toSnakeClothing(clothing))
      if (this.data.fromOnboarding) {
        const eventChannel = this.getOpenerEventChannel()
        eventChannel.emit('clothingAdded')
        wx.navigateBack()
      } else {
        wx.showModal({
          title: '保存成功',
          content: '衣物已添加到衣橱',
          confirmText: '继续添加',
          cancelText: '返回衣橱',
          success: (res) => {
            if (res.confirm) {
              this.resetForm()
            } else {
              wx.navigateBack()
            }
          }
        })
      }
    } finally {
      this.setData({ saving: false })
    }
  },

  resetForm() {
    this.setData({
      photoUrl: '',
      uploading: false,
      recognitionNotes: '',
      selectedType: '',
      subTypeOptions: [],
      selectedSubType: '',
      selectedColor: '',
      selectedPattern: 'solid',
      selectedSeasons: {},
      selectedThickness: '',
      selectedStyleTags: {},
      brand: '',
      size: ''
    })
    this.updateFilteredColors()
  }
})

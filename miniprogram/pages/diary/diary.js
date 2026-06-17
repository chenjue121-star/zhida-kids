const api = require('../../utils/api')
const Theme = require('../../utils/theme')
const { toCamelClothing, toCamelDiary, toSnakeDiary } = require('../../utils/model')
const { CLOTHING_TYPES, CLOTHING_SUB_TYPES, COLORS, SCENES } = require('../../utils/constant')

Page({
  data: {
    year: 0,
    month: 0,
    weekdays: ['日', '一', '二', '三', '四', '五', '六'],
    calendarDays: [],
    selectedDate: '',
    selectedDiary: null,
    selectedDiaryClothing: [],
    diaries: [],
    diaryCount: 0,
    uniqueClothingCount: 0,
    editing: false,
    formNote: '',
    formMood: '',
    formRating: 0,
    formActualPhotoUrl: '',
    ratingOptions: [1, 2, 3, 4, 5],
    themeClass: Theme.getThemeClass(),
    themeBgString: Theme.getThemePageBg(),
    currentThemeKey: Theme.getTheme().key
  },

  async onShow() {
    const app = getApp()
    await app.ensureReady()
    this.setData({
      themeClass: Theme.getThemeClass(app.globalData.theme),
      themeBgString: Theme.getThemePageBg(app.globalData.theme),
      currentThemeKey: (app.globalData.theme || Theme.getTheme()).key
    })
    Theme.applyAllTheme(app.globalData.theme)
    if (!app.globalData.isLoggedIn) {
      wx.navigateTo({ url: '/pages/login/login' })
      return
    }
    const now = new Date()
    if (!this.data.year) {
      this.setData({ year: now.getFullYear(), month: now.getMonth() + 1 })
    }
    await this.buildCalendar()
  },

  async prevMonth() {
    let { year, month } = this.data
    month -= 1
    if (month === 0) {
      year -= 1
      month = 12
    }
    this.setData({ year, month, selectedDate: '', selectedDiary: null, editing: false })
    await this.buildCalendar()
  },

  async nextMonth() {
    let { year, month } = this.data
    month += 1
    if (month === 13) {
      year += 1
      month = 1
    }
    this.setData({ year, month, selectedDate: '', selectedDiary: null, editing: false })
    await this.buildCalendar()
  },

  async buildCalendar() {
    const app = getApp()
    const child = app.getCurrentChild()
    const diaries = child
      ? (await api.get('/diaries', { child_id: child.id, year: this.data.year, month: this.data.month })).map(toCamelDiary)
      : []
    const diaryMap = diaries.reduce((acc, item) => {
      acc[item.date] = item
      return acc
    }, {})

    const { year, month } = this.data
    const firstDay = new Date(year, month - 1, 1)
    const start = new Date(firstDay)
    start.setDate(firstDay.getDate() - firstDay.getDay())

    const todayStr = this.formatDate(new Date())
    const calendarDays = []
    for (let i = 0; i < 42; i += 1) {
      const current = new Date(start)
      current.setDate(start.getDate() + i)
      const dateStr = this.formatDate(current)
      calendarDays.push({
        dateStr,
        day: current.getDate(),
        isToday: dateStr === todayStr,
        isCurrentMonth: current.getMonth() + 1 === month,
        hasDiary: Boolean(diaryMap[dateStr])
      })
    }

    const monthDiaries = diaries.filter(d => {
      const date = new Date(d.date)
      return date.getFullYear() === year && date.getMonth() + 1 === month
    })
    const uniqueIds = new Set()
    monthDiaries.forEach(d => (d.clothingIds || []).forEach(id => uniqueIds.add(id)))

    this.setData({
      calendarDays,
      diaries,
      diaryCount: monthDiaries.length,
      uniqueClothingCount: uniqueIds.size
    })
  },

  async selectDate(e) {
    const date = e.currentTarget.dataset.date
    const diary = this.data.diaries.find(d => d.date === date) || null
    const selectedDiaryClothing = diary
      ? (await Promise.all((diary.clothingIds || []).map(id => api.get(`/clothing/${id}`).then(toCamelClothing).catch(() => null))))
        .filter(Boolean)
        .map(item => this.enrichClothing(item))
      : []

    if (diary) {
      const scene = SCENES.find(s => s.value === diary.scene)
      diary.sceneLabel = scene ? scene.label : diary.scene
    }

    this.setData({
      selectedDate: date,
      selectedDiary: diary,
      selectedDiaryClothing,
      editing: false,
      formNote: diary ? diary.note || '' : '',
      formMood: diary ? diary.mood || '' : '',
      formRating: diary ? diary.rating || 0 : 0,
      formActualPhotoUrl: diary ? diary.actualPhotoUrl || '' : ''
    })
  },

  startEdit() {
    const diary = this.data.selectedDiary
    if (!diary) return
    this.setData({
      editing: true,
      formNote: diary.note || '',
      formMood: diary.mood || '',
      formRating: diary.rating || 0,
      formActualPhotoUrl: diary.actualPhotoUrl || ''
    })
  },

  cancelEdit() {
    this.setData({ editing: false })
  },

  onNote(e) {
    this.setData({ formNote: e.detail.value })
  },

  onMood(e) {
    this.setData({ formMood: e.detail.value })
  },

  selectRating(e) {
    this.setData({ formRating: Number(e.currentTarget.dataset.rating) || 0 })
  },

  chooseActualPhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: async (res) => {
        const filePath = res.tempFiles[0].tempFilePath
        this.setData({ formActualPhotoUrl: filePath })
        const uploaded = await api.uploadImage(filePath)
        this.setData({ formActualPhotoUrl: uploaded.url })
      }
    })
  },

  async saveDiaryEdit() {
    const diary = this.data.selectedDiary
    if (!diary) return
    const payload = toSnakeDiary({
      ...diary,
      note: this.data.formNote,
      mood: this.data.formMood,
      rating: this.data.formRating,
      actualPhotoUrl: this.data.formActualPhotoUrl
    })
    const updated = toCamelDiary(await api.put(`/diaries/${diary.id}`, payload))
    this.setData({ editing: false })
    await this.buildCalendar()
    await this.selectDate({ currentTarget: { dataset: { date: updated.date } } })
    wx.showToast({ title: '日记已更新', icon: 'success' })
  },

  deleteDiary() {
    const diary = this.data.selectedDiary
    if (!diary) return
    wx.showModal({
      title: '删除日记',
      content: '确认删除这天的穿搭记录吗？衣物本身不会被删除。',
      confirmText: '删除',
      confirmColor: '#E17055',
      success: async (res) => {
        if (!res.confirm) return
        await api.del(`/diaries/${diary.id}`)
        this.setData({
          selectedDiary: null,
          selectedDiaryClothing: [],
          editing: false
        })
        await this.buildCalendar()
        wx.showToast({ title: '已删除', icon: 'success' })
      }
    })
  },

  enrichClothing(item) {
    if (!item) return null
    const typeInfo = CLOTHING_TYPES.find(t => t.value === item.type) || {}
    const subTypeInfo = (CLOTHING_SUB_TYPES[item.type] || []).find(s => s.value === item.subType) || {}
    const colorInfo = COLORS.find(c => c.value === item.mainColor) || {}
    return {
      ...item,
      typeIcon: typeInfo.icon || '👕',
      subTypeLabel: subTypeInfo.label || '',
      colorLabel: colorInfo.label || ''
    }
  },

  formatDate(date) {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  }
})

const THEME_KEY = 'themeKey'
const DEFAULT_THEME_KEY = 'sunny_green'

const THEMES = {
  sunny_green: {
    key: 'sunny_green',
    name: '晴日草木',
    description: '奶油白 · 草木绿 · 阳光金',
    tabBarSelectedColor: '#6BA65C',
    swatches: ['#6BA65C', '#EEF5E5', '#F2B84B'],
    tokens: {
      '--color-primary': '#6BA65C',
      '--color-primary-dark': '#558B48',
      '--color-primary-light': '#EEF5E5',
      '--color-primary-soft': '#F7FAF1',
      '--color-secondary': '#9BC48D',
      '--color-accent': '#F2B84B',
      '--color-accent-soft': '#FDF1D9',
      '--color-warm': '#F4896B',
      '--color-warm-soft': '#FBE9E2',
      '--color-note-bg': '#FFF4DC',
      '--color-success': '#5BA85A',
      '--color-warning': '#F2B84B',
      '--color-danger': '#E46553',
      '--color-text': '#2A2A28',
      '--color-text-secondary': '#6F6B60',
      '--color-text-light': '#B5B0A4',
      '--color-bg': '#FFF9EF',
      '--color-bg-soft': '#F7F1E4',
      '--color-bg-white': '#FFFFFF',
      '--color-border': '#EFE5D3',
      '--color-border-strong': '#DBCFA9'
    }
  },
  soft_lavender: {
    key: 'soft_lavender',
    name: '云朵薰衣草',
    description: '雾紫 · 奶油白 · 阳光金',
    tabBarSelectedColor: '#7B6FBF',
    swatches: ['#7B6FBF', '#EFECF8', '#F2B84B'],
    tokens: {
      '--color-primary': '#7B6FBF',
      '--color-primary-dark': '#5F539C',
      '--color-primary-light': '#EFECF8',
      '--color-primary-soft': '#F7F5FC',
      '--color-secondary': '#A99FD9',
      '--color-accent': '#F2B84B',
      '--color-accent-soft': '#FDF1D9',
      '--color-warm': '#F4896B',
      '--color-warm-soft': '#FBE9E2',
      '--color-note-bg': '#FFF4DC',
      '--color-success': '#5BA85A',
      '--color-warning': '#F2B84B',
      '--color-danger': '#E46553',
      '--color-text': '#2A2A38',
      '--color-text-secondary': '#6B6880',
      '--color-text-light': '#B4B1C5',
      '--color-bg': '#FAF9F5',
      '--color-bg-soft': '#F2F0EB',
      '--color-bg-white': '#FFFFFF',
      '--color-border': '#E8E3F0',
      '--color-border-strong': '#D5CEE8'
    }
  },
  peach_pink: {
    key: 'peach_pink',
    name: '蜜桃粉',
    description: '亲和粉 · 柔白 · 暖黄',
    tabBarSelectedColor: '#E57A86',
    swatches: ['#E57A86', '#FCE8EB', '#F5B14C'],
    tokens: {
      '--color-primary': '#E57A86',
      '--color-primary-dark': '#C8596A',
      '--color-primary-light': '#FCE8EB',
      '--color-primary-soft': '#FDF3F4',
      '--color-secondary': '#F0A3AD',
      '--color-accent': '#F5B14C',
      '--color-accent-soft': '#FDF1D9',
      '--color-warm': '#F4896B',
      '--color-warm-soft': '#FBE9E2',
      '--color-note-bg': '#FFF4DC',
      '--color-success': '#5BA85A',
      '--color-warning': '#F5B14C',
      '--color-danger': '#E46553',
      '--color-text': '#352828',
      '--color-text-secondary': '#7A6868',
      '--color-text-light': '#C2B0B0',
      '--color-bg': '#FFF6F2',
      '--color-bg-soft': '#FBEDE8',
      '--color-bg-white': '#FFFFFF',
      '--color-border': '#F3DEE1',
      '--color-border-strong': '#E8C6CD'
    }
  },
  fresh_blue: {
    key: 'fresh_blue',
    name: '清爽海蓝',
    description: '海蓝 · 浅青 · 阳光黄',
    tabBarSelectedColor: '#3D8BB1',
    swatches: ['#3D8BB1', '#DDECF5', '#F2B84B'],
    tokens: {
      '--color-primary': '#3D8BB1',
      '--color-primary-dark': '#2A6A8D',
      '--color-primary-light': '#DDECF5',
      '--color-primary-soft': '#EEF6FB',
      '--color-secondary': '#6FB0CF',
      '--color-accent': '#F2B84B',
      '--color-accent-soft': '#FDF1D9',
      '--color-warm': '#F4896B',
      '--color-warm-soft': '#FBE9E2',
      '--color-note-bg': '#FFF4DC',
      '--color-success': '#5BA85A',
      '--color-warning': '#F2B84B',
      '--color-danger': '#E46553',
      '--color-text': '#202E36',
      '--color-text-secondary': '#5F7684',
      '--color-text-light': '#9FB0BA',
      '--color-bg': '#F5FAFC',
      '--color-bg-soft': '#E8F1F6',
      '--color-bg-white': '#FFFFFF',
      '--color-border': '#D5E3EC',
      '--color-border-strong': '#B9CFDE'
    }
  }
}

function getTheme(themeKey) {
  const key = themeKey || wx.getStorageSync(THEME_KEY) || DEFAULT_THEME_KEY
  return THEMES[key] || THEMES[DEFAULT_THEME_KEY]
}

function setTheme(themeKey) {
  const theme = getTheme(themeKey)
  wx.setStorageSync(THEME_KEY, theme.key)
  return theme
}

function getThemeClass(theme) {
  const current = theme || getTheme()
  return `theme-${current.key}`
}

function getThemeToken(tokenName, theme) {
  const current = theme || getTheme()
  return current.tokens[tokenName] || ''
}

function getThemeStyle(theme) {
  return ''
}

function applyTabBarTheme(theme) {
  const current = theme || getTheme()
  if (typeof wx.setTabBarStyle !== 'function') return
  wx.setTabBarStyle({
    color: current.tokens['--color-text-light'],
    selectedColor: current.tabBarSelectedColor,
    backgroundColor: current.tokens['--color-bg-white'],
    borderStyle: 'white'
  })
  if (typeof wx.setTabBarItem !== 'function') return
  const tabItems = [
    { index: 0, key: 'index' },
    { index: 1, key: 'wardrobe' },
    { index: 2, key: 'diary' },
    { index: 3, key: 'profile' }
  ]
  tabItems.forEach(item => {
    const iconPath = `assets/tabbar/${current.key}/${item.key}.png`
    const selectedIconPath = `assets/tabbar/${current.key}/${item.key}-active.png`
    try {
      wx.setTabBarItem({
        index: item.index,
        iconPath: iconPath,
        selectedIconPath: selectedIconPath
      })
    } catch (e) {}
  })
}

function applyNavBarTheme(theme) {
  const current = theme || getTheme()
  if (typeof wx.setNavigationBarColor !== 'function') return
  try {
    wx.setNavigationBarColor({
      frontColor: '#2A2A28',
      backgroundColor: current.tokens['--color-bg-white'],
      animation: { duration: 200, timingFunc: 'easeIn' }
    })
  } catch (e) {}
}

function applyAllTheme(theme) {
  applyTabBarTheme(theme)
  applyNavBarTheme(theme)
}

function getThemePageBg(theme) {
  const t = (theme || getTheme()).tokens
  return `linear-gradient(180deg, ${t['--color-primary-light']} 0%, ${t['--color-bg']} 40%, ${t['--color-bg-white']} 100%)`
}

function getThemePrimary(theme) {
  return (theme || getTheme()).tokens['--color-primary']
}

function getThemeText(theme) {
  return (theme || getTheme()).tokens['--color-text']
}

function getThemeBorder(theme) {
  return (theme || getTheme()).tokens['--color-border']
}

function listThemes() {
  return Object.keys(THEMES).map(key => THEMES[key])
}

module.exports = {
  THEMES,
  DEFAULT_THEME_KEY,
  getTheme,
  setTheme,
  getThemeClass,
  getThemeToken,
  getThemeStyle,
  getThemePageBg,
  getThemePrimary,
  getThemeText,
  getThemeBorder,
  applyTabBarTheme,
  applyNavBarTheme,
  applyAllTheme,
  listThemes
}

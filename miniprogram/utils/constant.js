module.exports = {
  CLOTHING_TYPES: [
    { value: 'top', label: '上衣', icon: '👕' },
    { value: 'pants', label: '裤子', icon: '👖' },
    { value: 'skirt', label: '裙子', icon: '👗' },
    { value: 'outerwear', label: '外套', icon: '🧥' },
    { value: 'shoes', label: '鞋子', icon: '👟' },
    { value: 'hat', label: '帽子', icon: '🧢' },
    { value: 'accessory', label: '配饰', icon: '🎀' },
    { value: 'set', label: '套装', icon: '👔' },
    { value: 'innerwear', label: '内搭', icon: '🎽' },
    { value: 'babywear', label: '婴童服', icon: '🍼' },
    { value: 'sleepwear', label: '睡衣/睡袋', icon: '🌙' }
  ],

  CLOTHING_SUB_TYPES: {
    top: [
      { value: 'tshirt', label: 'T恤' },
      { value: 'shirt', label: '衬衫' },
      { value: 'hoodie', label: '卫衣' },
      { value: 'sweater', label: '毛衣' },
      { value: 'polo', label: 'Polo衫' },
      { value: 'vest', label: '马甲/背心' }
    ],
    pants: [
      { value: 'jeans', label: '牛仔裤' },
      { value: 'casual_pants', label: '休闲裤' },
      { value: 'shorts', label: '短裤' },
      { value: 'sweatpants', label: '运动裤' },
      { value: 'leggings', label: '打底裤' },
      { value: 'bib_pants', label: '背带裤' },
      { value: 'sock_pants', label: '袜裤' }
    ],
    skirt: [
      { value: 'short_skirt', label: '短裙' },
      { value: 'long_skirt', label: '长裙' },
      { value: 'dress', label: '连衣裙' },
      { value: 'tutu', label: '蓬蓬裙' }
    ],
    outerwear: [
      { value: 'jacket', label: '夹克' },
      { value: 'down_jacket', label: '羽绒服' },
      { value: 'windbreaker', label: '风衣' },
      { value: 'cardigan', label: '开衫' },
      { value: 'coat', label: '大衣' },
      { value: 'cape', label: '披风/斗篷' }
    ],
    shoes: [
      { value: 'sneakers', label: '运动鞋' },
      { value: 'sandals', label: '凉鞋' },
      { value: 'boots', label: '靴子' },
      { value: 'casual_shoes', label: '休闲鞋' },
      { value: 'slippers', label: '拖鞋' },
      { value: 'toddler_shoes', label: '学步鞋' },
      { value: 'crib_shoes', label: '婴儿鞋' }
    ],
    hat: [
      { value: 'cap', label: '棒球帽' },
      { value: 'bucket_hat', label: '渔夫帽' },
      { value: 'beanie', label: '毛线帽' },
      { value: 'sun_hat', label: '遮阳帽' }
    ],
    accessory: [
      { value: 'scarf', label: '围巾' },
      { value: 'gloves', label: '手套' },
      { value: 'bag', label: '包包' },
      { value: 'hairband', label: '发饰' },
      { value: 'socks', label: '袜子' },
      { value: 'bib', label: '口水巾' },
      { value: 'feeding_bib', label: '围嘴/饭兜' },
      { value: 'burp_cloth', label: '拍嗝巾' },
      { value: 'blanket', label: '小盖毯' }
    ],
    set: [
      { value: 'casual_set', label: '休闲套装' },
      { value: 'sport_set', label: '运动套装' },
      { value: 'formal_set', label: '正装套装' }
    ],
    innerwear: [
      { value: 'thermal', label: '保暖内衣' },
      { value: 'undershirt', label: '打底衫' }
    ],
    babywear: [
      { value: 'onesie', label: '连体衣' },
      { value: 'romper', label: '爬服' },
      { value: 'bodysuit', label: '包屁衣' },
      { value: 'coverall', label: '哈衣' },
      { value: 'swaddle', label: '襁褓/包巾' }
    ],
    sleepwear: [
      { value: 'pajamas', label: '睡衣' },
      { value: 'sleep_sack', label: '睡袋' },
      { value: 'robe', label: '睡袍' }
    ]
  },

  COLORS: [
    { value: 'white', label: '白色', hex: '#FFFFFF', group: 'basic' },
    { value: 'black', label: '黑色', hex: '#000000', group: 'basic' },
    { value: 'gray', label: '灰色', hex: '#808080', group: 'basic' },
    { value: 'red', label: '红色', hex: '#E74C3C', group: 'basic' },
    { value: 'orange', label: '橙色', hex: '#F39C12', group: 'basic' },
    { value: 'yellow', label: '黄色', hex: '#FFD700', group: 'basic' },
    { value: 'green', label: '绿色', hex: '#27AE60', group: 'basic' },
    { value: 'blue', label: '蓝色', hex: '#3498DB', group: 'basic' },
    { value: 'purple', label: '紫色', hex: '#8E44AD', group: 'basic' },
    { value: 'pink', label: '粉色', hex: '#FFB6C1', group: 'pastel' },
    { value: 'peach', label: '蜜桃色', hex: '#FFC3A0', group: 'pastel' },
    { value: 'mint', label: '薄荷绿', hex: '#A8E6CF', group: 'pastel' },
    { value: 'sky_blue', label: '天蓝色', hex: '#87CEEB', group: 'pastel' },
    { value: 'lavender', label: '薰衣草紫', hex: '#CDB4DB', group: 'pastel' },
    { value: 'cream', label: '奶油色', hex: '#FFF4D6', group: 'neutral' },
    { value: 'beige', label: '米色', hex: '#F5DEB3', group: 'neutral' },
    { value: 'khaki', label: '卡其色', hex: '#C3B091', group: 'neutral' },
    { value: 'brown', label: '棕色', hex: '#8B4513', group: 'neutral' },
    { value: 'coffee', label: '咖啡色', hex: '#6F4E37', group: 'neutral' },
    { value: 'navy', label: '藏青', hex: '#000080', group: 'dark' },
    { value: 'burgundy', label: '酒红色', hex: '#800020', group: 'dark' },
    { value: 'forest_green', label: '墨绿色', hex: '#1B4D3E', group: 'dark' },
    { value: 'charcoal', label: '炭灰色', hex: '#36454F', group: 'dark' },
    { value: 'denim', label: '牛仔蓝', hex: '#4169E1', group: 'special' },
    { value: 'gold', label: '金色', hex: '#D4AF37', group: 'special' },
    { value: 'silver', label: '银色', hex: '#C0C0C0', group: 'special' },
    { value: 'neon_green', label: '荧光绿', hex: '#39FF14', group: 'special' },
    { value: 'multicolor', label: '多色/彩色', hex: 'linear-gradient(135deg,#FF6B81,#FFD86B,#5BA557,#6C8CFF)', group: 'special' }
  ],

  COLOR_GROUPS: [
    { value: 'all', label: '全部' },
    { value: 'basic', label: '基础色' },
    { value: 'pastel', label: '粉彩色' },
    { value: 'neutral', label: '中性色' },
    { value: 'dark', label: '深色' },
    { value: 'special', label: '特殊色' }
  ],

  PATTERNS: [
    { value: 'solid', label: '纯色' },
    { value: 'stripe', label: '条纹' },
    { value: 'plaid', label: '格子' },
    { value: 'print', label: '印花' },
    { value: 'cartoon', label: '卡通图案' },
    { value: 'floral', label: '碎花' },
    { value: 'polka_dot', label: '波点' },
    { value: 'animal', label: '动物' },
    { value: 'letter', label: '字母' },
    { value: 'number', label: '数字' },
    { value: 'star', label: '星星' },
    { value: 'heart', label: '爱心' },
    { value: 'cloud', label: '云朵' },
    { value: 'rainbow', label: '彩虹' },
    { value: 'dinosaur', label: '恐龙' },
    { value: 'car', label: '汽车' },
    { value: 'embroidery', label: '刺绣' },
    { value: 'colorblock', label: '拼色' },
    { value: 'gradient', label: '渐变' },
    { value: 'contrast', label: '撞色' },
    { value: 'leopard', label: '豹纹' }
  ],

  SEASONS: [
    { value: 'spring', label: '春' },
    { value: 'summer', label: '夏' },
    { value: 'autumn', label: '秋' },
    { value: 'winter', label: '冬' },
    { value: 'all', label: '四季' }
  ],

  THICKNESS: [
    { value: 'thin', label: '薄款' },
    { value: 'normal', label: '常规' },
    { value: 'thick', label: '加厚' },
    { value: 'fleece', label: '加绒' }
  ],

  STYLE_TAGS: [
    { value: 'casual', label: '休闲', emoji: '👕' },
    { value: 'sporty', label: '运动', emoji: '⚽' },
    { value: 'formal', label: '正式', emoji: '🎩' },
    { value: 'cute', label: '可爱', emoji: '🎀' },
    { value: 'cool', label: '酷帅', emoji: '🕶' },
    { value: 'korean', label: '韩系', emoji: '🇰' },
    { value: 'japanese', label: '日系', emoji: '🌸' },
    { value: 'preppy', label: '学院风', emoji: '📚' },
    { value: 'minimalist', label: '简约', emoji: '◻' }
  ],

  SCENES: [
    { value: 'home', label: '日常在家', icon: '🏠' },
    { value: 'school', label: '上幼儿园', icon: '🏫' },
    { value: 'outdoor', label: '户外活动', icon: '⛳' },
    { value: 'shopping', label: '逛街商场', icon: '🛍️' },
    { value: 'party', label: '聚会派对', icon: '🎉' },
    { value: 'travel', label: '拍照出行', icon: '📸' }
  ],

  SKIN_TONES: [
    { value: 'fair', label: '白皙', color: '#FFE4D6' },
    { value: 'natural', label: '自然', color: '#E8C4A0' },
    { value: 'dark', label: '偏黑', color: '#B8865A' }
  ],

  CLOTHING_STATUS: [
    { value: 'active', label: '在穿' },
    { value: 'stored', label: '收纳' },
    { value: 'retired', label: '已淘汰' }
  ]
}

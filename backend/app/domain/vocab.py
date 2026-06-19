CLOTHING_TYPES = [
    "top", "pants", "skirt", "outerwear", "shoes", "hat", "accessory", "set", "innerwear", "babywear", "sleepwear",
]
CLOTHING_SUB_TYPES = [
    "tshirt", "shirt", "hoodie", "sweater", "polo", "vest", "jeans", "casual_pants", "shorts", "sweatpants",
    "leggings", "bib_pants", "sock_pants", "short_skirt", "long_skirt", "dress", "tutu", "jacket",
    "down_jacket", "windbreaker", "cardigan", "coat", "cape", "sneakers", "sandals", "boots", "casual_shoes",
    "slippers", "toddler_shoes", "crib_shoes", "cap", "bucket_hat", "beanie", "sun_hat", "scarf", "gloves",
    "bag", "hairband", "socks", "bib", "feeding_bib", "burp_cloth", "blanket", "casual_set", "sport_set",
    "formal_set", "thermal", "undershirt", "onesie", "romper", "bodysuit", "coverall", "swaddle", "pajamas",
    "sleep_sack", "robe",
]
COLORS = [
    "white", "black", "gray", "red", "orange", "yellow", "green", "blue", "purple", "pink", "peach", "mint",
    "sky_blue", "lavender", "cream", "beige", "khaki", "brown", "coffee", "navy", "burgundy", "forest_green",
    "charcoal", "denim", "gold", "silver", "neon_green", "multicolor",
]
PATTERNS = [
    "solid", "stripe", "plaid", "print", "cartoon", "floral", "polka_dot", "animal", "letter", "number",
    "star", "heart", "cloud", "rainbow", "dinosaur", "car", "embroidery", "colorblock", "gradient", "contrast",
    "leopard",
]
SEASONS = ["spring", "summer", "autumn", "winter", "all"]
THICKNESS = ["thin", "normal", "thick", "fleece"]
STYLE_TAGS = ["casual", "sporty", "formal", "cute", "cool", "korean", "japanese", "preppy", "minimalist"]
RECOGNITION_FIELD_SCORE_META = {
    "type": {"category": "required", "weight": 28},
    "main_color": {"category": "required", "weight": 20},
    "thickness": {"category": "required", "weight": 18},
    "pattern": {"category": "optional", "weight": 10},
    "style_tags": {"category": "optional", "weight": 10},
    "season": {"category": "optional", "weight": 8},
    "sub_type": {"category": "optional", "weight": 4},
    "brand": {"category": "informational", "weight": 2},
    "size": {"category": "informational", "weight": 2},
}

_TYPE_ALIAS: dict[str, str] = {
    "上衣": "top", "t恤": "top", "tee": "top", "衬衫": "top", "毛衣": "top", "卫衣": "top",
    "马甲": "top", "背心": "top",
    "裤子": "pants", "裤": "pants", "牛仔裤": "pants", "长裤": "pants",
    "短裤": "pants", "运动裤": "pants", "打底裤": "pants",
    "裙子": "skirt", "裙": "skirt", "短裙": "skirt", "长裙": "skirt",
    "外套": "outerwear", "夹克": "outerwear", "羽绒服": "outerwear", "大衣": "outerwear",
    "风衣": "outerwear",
    "鞋子": "shoes", "鞋": "shoes", "运动鞋": "shoes", "凉鞋": "shoes", "靴子": "shoes",
    "学步鞋": "shoes", "拖鞋": "shoes",
    "帽子": "hat", "帽": "hat",
    "配饰": "accessory", "配件": "accessory", "围巾": "accessory", "手套": "accessory",
    "包": "accessory", "包包": "accessory", "发带": "accessory", "袜子": "accessory",
    "围兜": "accessory", "口水巾": "accessory",
    "套装": "set", "两件套": "set", "三件套": "set",
    "内衣": "innerwear", "秋衣": "innerwear", "秋裤": "innerwear",
    "婴儿服": "babywear", "连体衣": "babywear", "哈衣": "babywear", "爬服": "babywear",
    "睡衣": "sleepwear", "睡袋": "sleepwear",
}

_COLOR_ALIAS: dict[str, str] = {
    "白": "white", "白色": "white", "米白": "white",
    "黑": "black", "黑色": "black",
    "灰": "gray", "灰色": "gray", "浅灰": "gray", "深灰": "gray",
    "红": "red", "红色": "red", "大红": "red",
    "橙": "orange", "橙色": "orange", "橘": "orange", "橘色": "orange",
    "黄": "yellow", "黄色": "yellow", "金黄": "yellow",
    "绿": "green", "绿色": "green", "草绿": "green", "浅绿": "green",
    "蓝": "blue", "蓝色": "blue", "深蓝": "blue", "浅蓝": "blue",
    "紫": "purple", "紫色": "purple",
    "粉": "pink", "粉色": "pink", "粉红": "pink", "浅粉": "pink",
    "桃色": "peach", "桃粉": "peach",
    "薄荷": "mint", "薄荷绿": "mint",
    "天蓝": "sky_blue", "天空蓝": "sky_blue", "湖蓝": "sky_blue",
    "淡紫": "lavender", "薰衣草": "lavender", "浅紫": "lavender",
    "奶油": "cream", "奶油色": "cream",
    "米色": "beige", "米": "beige",
    "卡其": "khaki", "卡其色": "khaki",
    "棕": "brown", "棕色": "brown", "深棕": "brown",
    "咖啡": "coffee", "咖啡色": "coffee",
    "藏青": "navy", "藏蓝": "navy", "深蓝": "navy", "藏青色": "navy",
    "酒红": "burgundy", "酒红色": "burgundy", "枣红": "burgundy",
    "森林绿": "forest_green", "墨绿": "forest_green",
    "炭灰": "charcoal", "炭黑": "charcoal",
    "牛仔": "denim", "牛仔蓝": "denim",
    "金": "gold", "金色": "gold",
    "银": "silver", "银色": "silver",
    "荧光绿": "neon_green", "亮绿": "neon_green",
    "多色": "multicolor", "花色": "multicolor", "彩色": "multicolor", "印花": "multicolor",
}

_PATTERN_ALIAS: dict[str, str] = {
    "纯色": "solid", "素色": "solid",
    "条纹": "stripe", "横条纹": "stripe", "竖条纹": "stripe",
    "格纹": "plaid", "格子": "plaid", "格": "plaid", "格仔": "plaid",
    "图案": "print", "印花": "print",
    "卡通": "cartoon", "卡通人物": "cartoon", "动漫": "cartoon",
    "花朵": "floral", "碎花": "floral", "花": "floral",
    "波点": "polka_dot", "圆点": "polka_dot",
    "动物": "animal",
    "字母": "letter", "字母印花": "letter",
    "数字": "number",
    "星星": "star", "五角星": "star",
    "爱心": "heart", "心形": "heart",
    "云朵": "cloud", "白云": "cloud",
    "彩虹": "rainbow",
    "恐龙": "dinosaur",
    "汽车": "car", "小汽车": "car",
    "刺绣": "embroidery", "绣花": "embroidery",
    "撞色": "colorblock", "色块": "colorblock", "拼接": "colorblock",
    "渐变": "gradient", "渐变色": "gradient",
    "撞色拼接": "contrast",
    "豹纹": "leopard", "动物纹": "leopard",
}

_THICKNESS_ALIAS: dict[str, str] = {
    "薄": "thin", "薄款": "thin", "单层": "thin", "网眼": "thin", "夏季": "thin",
    "普通": "normal", "常规": "normal", "中等": "normal", "春秋": "normal",
    "厚": "thick", "厚款": "thick", "双层": "thick", "夹棉": "thick", "冬季": "thick",
    "加绒": "fleece", "抓绒": "fleece", "摇粒绒": "fleece", "羊羔绒": "fleece",
    "绒": "fleece",
}

_SEASON_ALIAS: dict[str, str] = {
    "春": "spring", "春季": "spring",
    "夏": "summer", "夏季": "summer",
    "秋": "autumn", "秋季": "autumn",
    "冬": "winter", "冬季": "winter",
    "全年": "all", "四季": "all", "通用": "all",
}

_STYLE_ALIAS: dict[str, str] = {
    "休闲": "casual", "日常": "casual",
    "运动": "sporty", "运动风": "sporty",
    "正式": "formal", "礼服": "formal",
    "可爱": "cute", "甜美": "cute",
    "酷": "cool", "酷帅": "cool", "潮": "cool",
    "韩系": "korean", "韩版": "korean", "韩风": "korean",
    "日系": "japanese", "日版": "japanese", "和风": "japanese",
    "学院": "preppy", "学院风": "preppy", "校园": "preppy",
    "简约": "minimalist", "简约风": "minimalist", "极简": "minimalist",
}

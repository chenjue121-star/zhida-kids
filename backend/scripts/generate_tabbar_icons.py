"""生成智搭小程序 TabBar 图标（多主题支持）
为每个主题生成 4×2 张 162x162 PNG：index/wardrobe/diary/profile × normal/active
"""
from PIL import Image, ImageDraw
import os

# 固定输出目录（相对小程序根目录）
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       'miniprogram', 'assets', 'tabbar')
os.makedirs(OUT_DIR, exist_ok=True)

SIZE = 162
STROKE = 9

# 主题色定义（与 utils/theme.js 一致）
THEMES = {
    'sunny_green': {
        'name': '晴日草木',
        'primary': (91, 165, 87, 255),
        'light': (234, 245, 229, 255),
        'accent': (255, 216, 107, 255),
        'gray': (140, 148, 155, 255),
    },
    'soft_lavender': {
        'name': '云朵薰衣草',
        'primary': (123, 97, 255, 255),
        'light': (236, 231, 255, 255),
        'accent': (255, 216, 107, 255),
        'gray': (158, 155, 175, 255),
    },
    'peach_pink': {
        'name': '蜜桃粉',
        'primary': (255, 107, 129, 255),
        'light': (255, 228, 232, 255),
        'accent': (253, 203, 110, 255),
        'gray': (158, 155, 165, 255),
    },
    'fresh_blue': {
        'name': '清爽海蓝',
        'primary': (47, 143, 184, 255),
        'light': (228, 244, 247, 255),
        'accent': (255, 214, 107, 255),
        'gray': (134, 148, 158, 255),
    },
}

WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def new_canvas():
    return Image.new('RGBA', (SIZE, SIZE), TRANSPARENT)


# ---------- 1. 今日穿搭：衣服 + 小太阳 ----------
def draw_outfit(selected, theme):
    img = new_canvas()
    d = ImageDraw.Draw(img)
    main_color = theme['primary'] if selected else theme['gray']
    bg_fill = theme['light'] if selected else (245, 248, 252, 255)

    cx, cy = SIZE // 2, SIZE // 2 + 6
    shoulder_y = 46
    body_top_y = 70
    body_bottom_y = 138
    body_left_x = cx - 48
    body_right_x = cx + 48

    # 左袖
    d.pieslice([body_left_x - 20, shoulder_y - 10, body_left_x + 34, shoulder_y + 60],
               120, 260, fill=main_color)
    # 右袖
    d.pieslice([body_right_x - 34, shoulder_y - 10, body_right_x + 20, shoulder_y + 60],
               280, 60, fill=main_color)
    # 身体主体
    d.rounded_rectangle([body_left_x + 2, body_top_y - 4, body_right_x - 2, body_bottom_y],
                        radius=14, fill=main_color)
    # 领口
    d.ellipse([cx - 18, shoulder_y - 22, cx + 18, shoulder_y + 20], fill=WHITE)
    # 领口V形
    d.line([cx - 10, shoulder_y - 4, cx, shoulder_y + 16], fill=main_color, width=3)
    d.line([cx + 10, shoulder_y - 4, cx, shoulder_y + 16], fill=main_color, width=3)
    # 衣服底部开叉
    d.rectangle([cx - 4, body_bottom_y - 16, cx + 4, body_bottom_y], fill=WHITE)

    if selected:
        sun_cx, sun_cy = SIZE - 32, 28
        d.ellipse([sun_cx - 16, sun_cy - 16, sun_cx + 16, sun_cy + 16], fill=theme['accent'])
        d.ellipse([sun_cx - 10, sun_cy - 10, sun_cx + 4, sun_cy + 4],
                  fill=(255, 238, 155, 255))

    return img


# ---------- 2. 衣橱：衣柜门 ----------
def draw_wardrobe(selected, theme):
    img = new_canvas()
    d = ImageDraw.Draw(img)
    main_color = theme['primary'] if selected else theme['gray']
    light_fill = theme['light'] if selected else (245, 248, 252, 255)

    frame_left, frame_top = 28, 22
    frame_right, frame_bottom = SIZE - 28, SIZE - 20
    d.rounded_rectangle([frame_left, frame_top, frame_right, frame_bottom],
                        radius=18, fill=light_fill, outline=main_color, width=STROKE)
    mid_x = (frame_left + frame_right) // 2
    d.line([mid_x, frame_top + 12, mid_x, frame_bottom - 12], fill=main_color, width=STROKE - 2)

    handle_y = (frame_top + frame_bottom) // 2 + 8
    handle_r = 5
    d.ellipse([mid_x - 18 - handle_r, handle_y - handle_r, mid_x - 18 + handle_r, handle_y + handle_r],
              fill=main_color)
    d.ellipse([mid_x + 18 - handle_r, handle_y - handle_r, mid_x + 18 + handle_r, handle_y + handle_r],
              fill=main_color)

    d.rectangle([frame_left + 12, frame_bottom, frame_left + 22, frame_bottom + 6], fill=main_color)
    d.rectangle([frame_right - 22, frame_bottom, frame_right - 12, frame_bottom + 6], fill=main_color)

    if selected:
        d.ellipse([mid_x - 5, frame_top - 14, mid_x + 5, frame_top - 4], fill=theme['accent'])
        d.rectangle([mid_x - 16, frame_top - 6, mid_x + 16, frame_top - 2], fill=main_color)

    return img


# ---------- 3. 日记：书本 ----------
def draw_diary(selected, theme):
    img = new_canvas()
    d = ImageDraw.Draw(img)
    main_color = theme['primary'] if selected else theme['gray']
    book_fill = theme['light'] if selected else (245, 248, 252, 255)

    book_left, book_top = 22, 40
    book_right, book_bottom = SIZE - 22, SIZE - 34
    d.rounded_rectangle([book_left, book_top, book_right, book_bottom],
                        radius=12, fill=book_fill, outline=main_color, width=STROKE)
    d.rectangle([book_left, book_top + 8, book_left + 10, book_bottom - 8], fill=main_color)

    line_color = main_color
    text_y_start = book_top + 26
    text_x_left = book_left + 26
    text_x_right = book_right - 14
    for i, length in enumerate([0.85, 0.7, 0.9, 0.55, 0.8, 0.6]):
        y = text_y_start + i * 14
        right = text_x_left + int((text_x_right - text_x_left) * length)
        d.line([text_x_left, y, right, y], fill=line_color, width=4)

    label_left = book_left + 30
    label_right = book_right - 30
    label_top = book_top - 10
    label_bottom = book_top + 18
    d.rounded_rectangle([label_left, label_top, label_right, label_bottom],
                        radius=6, fill=theme['accent'] if selected else (220, 225, 230, 255),
                        outline=main_color, width=STROKE - 2)

    if selected:
        hc = (255, 140, 150, 255)
        heart_cx, heart_cy = (label_left + label_right) // 2, (label_top + label_bottom) // 2
        d.ellipse([heart_cx - 8, heart_cy - 6, heart_cx, heart_cy + 2], fill=hc)
        d.ellipse([heart_cx, heart_cy - 6, heart_cx + 8, heart_cy + 2], fill=hc)
        d.polygon([(heart_cx - 8, heart_cy - 1), (heart_cx + 8, heart_cy - 1), (heart_cx, heart_cy + 9)], fill=hc)

    return img


# ---------- 4. 我的：头像 ----------
def draw_profile(selected, theme):
    img = new_canvas()
    d = ImageDraw.Draw(img)
    main_color = theme['primary'] if selected else theme['gray']
    light_fill = theme['light'] if selected else (245, 248, 252, 255)

    head_cx, head_cy = SIZE // 2, 54
    head_r = 30
    d.ellipse([head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r],
              fill=light_fill, outline=main_color, width=STROKE)

    eye_r = 3
    eye_y = head_cy - 2
    d.ellipse([head_cx - 12 - eye_r, eye_y - eye_r, head_cx - 12 + eye_r, eye_y + eye_r], fill=main_color)
    d.ellipse([head_cx + 12 - eye_r, eye_y - eye_r, head_cx + 12 + eye_r, eye_y + eye_r], fill=main_color)

    d.arc([head_cx - 10, head_cy + 2, head_cx + 10, head_cy + 18], 0, 180, fill=main_color, width=3)

    body_top = head_cy + head_r - 4
    body_bottom = SIZE - 20
    body_left_top = head_cx - 34
    body_right_top = head_cx + 34
    body_left_bottom = head_cx - 70
    body_right_bottom = head_cx + 70

    d.polygon([
        (body_left_top, body_top), (body_right_top, body_top),
        (body_right_bottom, body_bottom), (body_left_bottom, body_bottom),
    ], fill=light_fill)

    d.line([body_left_top, body_top, body_left_bottom, body_bottom],
           fill=main_color, width=STROKE)
    d.line([body_right_top, body_top, body_right_bottom, body_bottom],
           fill=main_color, width=STROKE)
    d.line([body_left_bottom, body_bottom, body_right_bottom, body_bottom],
           fill=main_color, width=STROKE)
    d.line([head_cx - 14, head_cy + head_r - 2, head_cx + 14, head_cy + head_r - 2],
           fill=main_color, width=STROKE - 2)

    btn_cx, btn_cy = SIZE // 2, body_top + 22
    d.ellipse([btn_cx - 4, btn_cy - 4, btn_cx + 4, btn_cy + 4], fill=main_color)

    if selected:
        star_cx, star_cy = SIZE - 26, 24
        d.ellipse([star_cx - 12, star_cy - 12, star_cx + 12, star_cy + 12], fill=theme['accent'])
        d.ellipse([star_cx - 6, star_cy - 6, star_cx + 2, star_cy + 2], fill=(255, 244, 180, 255))

    return img


def main():
    icons = [
        ('index', draw_outfit),
        ('wardrobe', draw_wardrobe),
        ('diary', draw_diary),
        ('profile', draw_profile),
    ]

    # 生成默认图标（sunny_green）
    default_theme = THEMES['sunny_green']
    for name, draw_fn in icons:
        draw_fn(False, default_theme).save(os.path.join(OUT_DIR, f'{name}.png'), 'PNG')
        draw_fn(True, default_theme).save(os.path.join(OUT_DIR, f'{name}-active.png'), 'PNG')
    print(f'✓ 默认图标 (sunny_green): {OUT_DIR}/{{index,wardrobe,diary,profile}}{{,-active}}.png')

    # 为每个主题生成一套（放在子目录或加前缀）
    for theme_key, theme in THEMES.items():
        theme_dir = os.path.join(OUT_DIR, theme_key)
        os.makedirs(theme_dir, exist_ok=True)
        for name, draw_fn in icons:
            draw_fn(False, theme).save(os.path.join(theme_dir, f'{name}.png'), 'PNG')
            draw_fn(True, theme).save(os.path.join(theme_dir, f'{name}-active.png'), 'PNG')
        print(f'  ✓ {theme_key} ({theme["name"]}): {theme_dir}')

    print(f'\n✅ 所有图标生成完成 → {OUT_DIR}')


if __name__ == '__main__':
    main()

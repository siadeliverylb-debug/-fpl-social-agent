"""Turn a "story" dict (from fetch_news.py) into a 1080x1080 branded PNG card
and a caption string ready to post."""

import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
FONT_PATH = os.path.join(HERE, "..", "assets", "templates", "fonts", "Roboto-Variable.ttf")
OUT_DIR = os.path.join(HERE, "..", "assets", "generated")

SIZE = 1080
BG_TOP = (13, 26, 22)      # near-black green
BG_BOTTOM = (30, 58, 45)   # deep FPL green
ACCENT = (0, 255, 135)     # FPL-ish neon green
WHITE = (245, 245, 245)
MUTED = (170, 190, 180)

BRAND = "@fantasy.coach.ai  |  @fantasycoachai"


def _font(size, weight=700):
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight, 100])  # [wght, wdth]
    except Exception:
        pass
    return f


def _gradient_bg():
    img = Image.new("RGB", (SIZE, SIZE), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / SIZE
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b))
    return img, draw


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _base_card(eyebrow, headline, subtext=None):
    img, draw = _gradient_bg()
    margin = 90

    draw.text((margin, margin), eyebrow.upper(), font=_font(38, 700), fill=ACCENT)
    draw.line([(margin, margin + 60), (margin + 90, margin + 60)], fill=ACCENT, width=6)

    headline_font = _font(88, 800)
    lines = _wrap(draw, headline, headline_font, SIZE - 2 * margin)
    y = SIZE // 2 - (len(lines) * 100) // 2
    for line in lines:
        draw.text((margin, y), line, font=headline_font, fill=WHITE)
        y += 100

    if subtext:
        sub_font = _font(42, 500)
        sub_lines = _wrap(draw, subtext, sub_font, SIZE - 2 * margin)
        for line in sub_lines:
            draw.text((margin, y + 10), line, font=sub_font, fill=MUTED)
            y += 56

    draw.text((margin, SIZE - margin), BRAND, font=_font(32, 600), fill=MUTED)
    return img


def render_card(story, out_path):
    t = story["type"]

    if t == "price_change":
        arrow = "UP" if story["direction"] == "rise" else "DOWN"
        eyebrow = f"PRICE {arrow}"
        headline = f"{story['player']} ({story['team']})"
        subtext = f"Now £{story['new_price_millions']}m  ({'+' if story['direction']=='rise' else '-'}£{story['delta_millions']}m)"
    elif t == "status_change":
        eyebrow = f"INJURY UPDATE - {story['status'].upper()}"
        headline = f"{story['player']} ({story['team']})"
        subtext = story["news"]
    elif t == "deadline_reminder":
        eyebrow = "DEADLINE ALERT"
        headline = f"GW{story['gw']} deadline in {story['bucket']}"
        subtext = "Lock in your transfers and captain now."
    elif t == "gw_recap":
        eyebrow = f"GW{story['gw']} RECAP"
        headline = f"Highest score: {story.get('highest_score', 'N/A')} pts"
        subtext = "Full breakdown in the caption."
    else:
        eyebrow = "FPL NEWS"
        headline = story.get("player", "Update")
        subtext = None

    img = _base_card(eyebrow, headline, subtext)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def build_caption(story):
    t = story["type"]
    tags = "#FPL #FantasyPremierLeague #FPLCommunity"

    if t == "price_change":
        arrow = "up" if story["direction"] == "rise" else "down"
        return (
            f"{story['player']} ({story['team']}) is {arrow} to £{story['new_price_millions']}m.\n\n"
            f"Own him? Selling or holding? {tags} #{story['team']}"
        )
    if t == "status_change":
        return (
            f"{story['player']} ({story['team']}) update: {story['status']}.\n"
            f"\"{story['news']}\"\n\n"
            f"How does this change your plans this GW? {tags}"
        )
    if t == "deadline_reminder":
        return (
            f"GW{story['gw']} deadline in {story['bucket']}. "
            f"Transfers, captain, chip calls -- lock it in now.\n\n{tags}"
        )
    if t == "gw_recap":
        return (
            f"GW{story['gw']} in the books. Highest score: {story.get('highest_score')} pts. "
            f"Most captained ID: {story.get('most_captained')}.\n\n"
            f"How did your team do? {tags}"
        )
    return f"FPL update. {tags}"


if __name__ == "__main__":
    demo_story = {
        "type": "price_change",
        "key": "demo",
        "player": "Haaland",
        "team": "MCI",
        "direction": "rise",
        "delta_millions": 0.1,
        "new_price_millions": 15.1,
    }
    out = os.path.join(OUT_DIR, "demo_price_change.png")
    render_card(demo_story, out)
    print("Saved:", out)
    print("Caption:\n", build_caption(demo_story))

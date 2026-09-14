"""Turn a "story" dict (from fetch_news.py) into a 1080x1080 branded PNG card
and a caption string ready to post. Cards lead with one big hero stat -- the
single most attention-grabbing number/fact -- rather than the player name,
since that's what stops the scroll."""

import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
FONT_PATH = os.path.join(HERE, "..", "assets", "templates", "fonts", "Roboto-Variable.ttf")
OUT_DIR = os.path.join(HERE, "..", "assets", "generated")

SIZE = 1080
BG_TOP = (13, 26, 22)      # near-black green
BG_BOTTOM = (30, 58, 45)   # deep FPL green
ACCENT = (0, 255, 135)     # FPL-ish neon green
ALERT = (255, 82, 82)      # urgency red (injuries, price falls)
WARN = (255, 176, 32)      # urgency amber (deadlines)
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


def _hero_card(eyebrow, hero, headline, subtext=None, hero_color=None):
    img, draw = _gradient_bg()
    margin = 90
    hero_color = hero_color or ACCENT

    draw.text((margin, margin), eyebrow.upper(), font=_font(36, 800), fill=hero_color)
    draw.line([(margin, margin + 58), (margin + 90, margin + 58)], fill=hero_color, width=6)

    hero_size = 230
    hero_font = _font(hero_size, 900)
    while draw.textlength(hero, font=hero_font) > SIZE - 2 * margin and hero_size > 90:
        hero_size -= 12
        hero_font = _font(hero_size, 900)
    hero_y = 270
    draw.text((margin, hero_y), hero, font=hero_font, fill=WHITE)

    headline_font = _font(56, 800)
    y = hero_y + hero_size + 30
    for line in _wrap(draw, headline, headline_font, SIZE - 2 * margin):
        draw.text((margin, y), line, font=headline_font, fill=hero_color)
        y += 68

    if subtext:
        sub_font = _font(38, 500)
        for line in _wrap(draw, subtext, sub_font, SIZE - 2 * margin):
            draw.text((margin, y + 16), line, font=sub_font, fill=MUTED)
            y += 50

    draw.text((margin, SIZE - margin), BRAND, font=_font(30, 600), fill=MUTED)
    return img


def render_card(story, out_path):
    t = story["type"]

    if t == "price_change":
        rising = story["direction"] == "rise"
        eyebrow = "PRICE RISE" if rising else "PRICE FALL"
        hero = f"£{story['new_price_millions']}M"
        headline = f"{story['player']} ({story['team']})"
        subtext = f"{'+' if rising else '-'}£{story['delta_millions']}m price change"
        hero_color = ACCENT if rising else ALERT
    elif t == "status_change":
        eyebrow = "INJURY ALERT"
        hero = story["status"].upper()
        headline = f"{story['player']} ({story['team']})"
        subtext = story["news"]
        hero_color = ALERT
    elif t == "deadline_reminder":
        eyebrow = "DEADLINE ALERT"
        hero = story["bucket"].upper()
        headline = f"GW{story['gw']} DEADLINE"
        subtext = "Lock in transfers and captain now."
        hero_color = WARN
    elif t == "gw_recap":
        eyebrow = f"GW{story['gw']} RECAP"
        hero = f"{story.get('highest_score', 'N/A')} PTS"
        headline = "TOP SCORE THIS GW"
        subtext = "Did your team beat it? Full breakdown in the caption."
        hero_color = ACCENT
    else:
        eyebrow = "FPL NEWS"
        hero = "UPDATE"
        headline = story.get("player", "")
        subtext = None
        hero_color = ACCENT

    img = _hero_card(eyebrow, hero, headline, subtext, hero_color)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def build_caption(story):
    t = story["type"]
    tags = "#FPL #FantasyPremierLeague #FPLCommunity"

    if t == "price_change":
        if story["direction"] == "rise":
            return (
                f"\U0001F4C8 {story['player']} ({story['team']}) is on the up -- now £{story['new_price_millions']}m.\n\n"
                f"Already own him, or bringing him in before he rises again? {tags} #{story['team']}"
            )
        return (
            f"\U0001F4C9 {story['player']} ({story['team']}) drops to £{story['new_price_millions']}m.\n\n"
            f"Panic sell or hold firm? {tags} #{story['team']}"
        )
    if t == "status_change":
        return (
            f"\U0001F6A8 INJURY ALERT: {story['player']} ({story['team']}) is {story['status']}.\n"
            f"\"{story['news']}\"\n\n"
            f"Does this wreck your GW plan? {tags}"
        )
    if t == "deadline_reminder":
        return (
            f"⏰ GW{story['gw']} deadline in {story['bucket']}! "
            f"Transfers, captain, chip calls -- lock it in NOW.\n\n{tags}"
        )
    if t == "gw_recap":
        return (
            f"\U0001F525 GW{story['gw']} is in the books. Top score: {story.get('highest_score')} pts. "
            f"Most captained ID: {story.get('most_captained')}.\n\n"
            f"Did YOU beat the top score? {tags}"
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

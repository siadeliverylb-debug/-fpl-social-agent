"""Turn a "story" dict (from fetch_news.py) into a 1080x1080 branded PNG card
and a caption string ready to post. Cards lead with one big hero stat -- the
single most attention-grabbing number/fact -- rather than the player name,
since that's what stops the scroll."""

import os
import random
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
FONT_PATH = os.path.join(HERE, "..", "assets", "templates", "fonts", "Roboto-Variable.ttf")
LOGO_PATH = os.path.join(HERE, "..", "assets", "templates", "logo", "logo.jpg")
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

# #FPL is always kept as the anchor tag; a couple more are rotated in from
# this pool so posts don't all carry the exact same hashtag set.
GENERAL_HASHTAG_POOL = [
    "#FPLCommunity",
    "#FantasyPremierLeague",
    "#FantasyFootball",
    "#FPLTips",
    "#PremierLeague",
    "#FPLTwitter",
    "#FPLFamily",
]


def _random_hashtags(n=2):
    return "#FPL " + " ".join(random.sample(GENERAL_HASHTAG_POOL, min(n, len(GENERAL_HASHTAG_POOL))))


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


def _circular_logo(size):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo = logo.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    logo.putalpha(mask)
    return logo


def _add_shapes(img, accent):
    """Low-alpha geometric accents behind the text -- a diagonal stripe in
    the bottom-left corner and a ring behind the hero stat -- so the card
    reads as designed rather than a flat color fill."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    w, h = img.size

    odraw.polygon([(0, h), (0, h - 320), (320, h)], fill=accent + (28,))
    odraw.polygon([(w, 0), (w, 220), (w - 220, 0)], fill=accent + (22,))
    odraw.ellipse((w - 560, 120, w - 40, 640), outline=accent + (35,), width=3)

    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


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


def _draw_triangle(draw, x, y, size, color, direction):
    """A filled triangle drawn as shapes rather than a font glyph -- unlike
    arrow/triangle unicode characters (e.g. ↓/↑), this renders
    correctly regardless of whether the card font has that glyph."""
    if direction == "down":
        pts = [(x, y), (x + size, y), (x + size / 2, y + size)]
    else:
        pts = [(x, y + size), (x + size, y + size), (x + size / 2, y)]
    draw.polygon(pts, fill=color)


def _hero_card(eyebrow, hero, headline, subtext=None, hero_color=None, hashtags=None):
    """`hero` is normally a string. It may instead be a list of segments to
    support inline shapes (e.g. rise/fall triangles) that a font glyph can't
    reliably provide: {"text": str, "color": optional} or
    {"shape": "up"|"down", "color": optional}."""
    img, _ = _gradient_bg()
    margin = 90
    hero_color = hero_color or ACCENT

    img = _add_shapes(img, hero_color)
    draw = ImageDraw.Draw(img)

    logo_size = 96
    logo = _circular_logo(logo_size)
    logo_pos = (SIZE - margin - logo_size, margin - 20)
    draw.ellipse(
        (logo_pos[0] - 4, logo_pos[1] - 4, logo_pos[0] + logo_size + 4, logo_pos[1] + logo_size + 4),
        outline=hero_color, width=3,
    )
    img.paste(logo, logo_pos, logo)
    draw = ImageDraw.Draw(img)

    draw.text((margin, margin), eyebrow.upper(), font=_font(36, 800), fill=hero_color)
    draw.line([(margin, margin + 58), (margin + 90, margin + 58)], fill=hero_color, width=6)

    hero_y = 270
    if isinstance(hero, list):
        hero_size = 230
        hero_font = _font(hero_size, 900)

        def _segments_width(font):
            w = 0
            for seg in hero:
                w += draw.textlength(seg["text"], font=font) if "text" in seg else font.size * 0.65
            return w

        while _segments_width(hero_font) > SIZE - 2 * margin and hero_size > 90:
            hero_size -= 12
            hero_font = _font(hero_size, 900)

        x = margin
        for seg in hero:
            if "text" in seg:
                draw.text((x, hero_y), seg["text"], font=hero_font, fill=seg.get("color", WHITE))
                x += draw.textlength(seg["text"], font=hero_font)
            else:
                tri_size = hero_size * 0.5
                tri_y = hero_y + hero_size * 0.32
                _draw_triangle(draw, x, tri_y, tri_size, seg.get("color", WHITE), seg["shape"])
                x += tri_size + hero_size * 0.12
    else:
        hero_size = 230
        hero_font = _font(hero_size, 900)
        while draw.textlength(hero, font=hero_font) > SIZE - 2 * margin and hero_size > 90:
            hero_size -= 12
            hero_font = _font(hero_size, 900)
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

    if hashtags:
        draw.text((margin, SIZE - margin - 50), hashtags, font=_font(30, 700), fill=hero_color)

    draw.text((margin, SIZE - margin), BRAND, font=_font(30, 600), fill=MUTED)
    return img


# category -> (eyebrow, hero text or None to fall back to the status label, color)
STATUS_CARD_META = {
    "injury": ("INJURY ALERT", None, ALERT),
    "suspension": ("SUSPENDED", "SUSPENDED", ALERT),
    "loan": ("LOAN MOVE", "ON LOAN", WARN),
    "transfer": ("TRANSFER NEWS", "TRANSFERRED", WARN),
    "departure": ("SQUAD NEWS", "DEPARTED", WARN),
    "availability": ("AVAILABILITY UPDATE", None, WARN),
}

# type -> (eyebrow, hero, color) -- hero is plain text, not emoji: the card
# font (Roboto) has no color-emoji glyphs and renders them as tofu boxes.
LIVE_EVENT_META = {
    "goal": ("GOAL", "GOAL!", ACCENT),
    "assist": ("ASSIST", "ASSIST", ACCENT),
    "yellow_card": ("YELLOW CARD", "BOOKED", WARN),
    "red_card": ("RED CARD", "SENT OFF", ALERT),
    "penalty_miss": ("PENALTY MISSED", "MISSED", ALERT),
    "penalty_save": ("PENALTY SAVED", "SAVED", ACCENT),
    "own_goal": ("OWN GOAL", "OWN GOAL", ALERT),
    "substitution": ("SUBSTITUTION", "SUB ON", ACCENT),
    "goal_disallowed": ("VAR DECISION", "NO GOAL", ALERT),
}


def _minute_str(story):
    minute = story.get("minute")
    if minute is None:
        return ""
    return f"{minute}'"


def render_card(story, out_path):
    t = story["type"]
    base_tags = _random_hashtags()
    hashtags = base_tags

    if t == "price_change":
        rising = story["direction"] == "rise"
        eyebrow = "PRICE RISE" if rising else "PRICE FALL"
        hero = f"£{story['new_price_millions']}M"
        headline = f"{story['player']} ({story['team']})"
        subtext = f"{'+' if rising else '-'}£{story['delta_millions']}m price change"
        hero_color = ACCENT if rising else ALERT
        hashtags = f"{base_tags} #{story['team']}"
    elif t == "price_changes":
        changes = story["changes"]
        rises = [c for c in changes if c["direction"] == "rise"]
        falls = [c for c in changes if c["direction"] == "fall"]
        eyebrow = "PRICE CHANGES"
        hero = [
            {"text": f"{len(falls)} "},
            {"shape": "down", "color": ALERT},
            {"text": f"  {len(rises)} "},
            {"shape": "up", "color": ACCENT},
        ]
        headline = "TONIGHT'S PRICE CHANGES"
        names = [c["player"] for c in changes]
        shown, extra = names[:12], names[12:]
        subtext = ", ".join(shown)
        if extra:
            subtext += f"  +{len(extra)} more -- full list in caption"
        hero_color = ALERT if len(falls) >= len(rises) else ACCENT
    elif t == "status_change":
        category = story.get("category", "availability")
        eyebrow, hero, hero_color = STATUS_CARD_META.get(category, STATUS_CARD_META["availability"])
        hero = hero or story["status"].upper()
        headline = f"{story['player']} ({story['team']})"
        subtext = story["news"]
        hashtags = f"{base_tags} #{story['team']}"
    elif t in ("form_hot", "form_cold"):
        hot = t == "form_hot"
        players_ = story["players"]
        top, rest = players_[0], players_[1:]
        eyebrow = "IN FORM" if hot else "STRUGGLING"
        hero = f"{top['form']:.1f} PPG"
        headline = f"{top['name']} ({top['team']})"
        rest_txt = ", ".join(f"{p['name']} {p['form']:.1f}" for p in rest)
        if hot:
            subtext = f"Also in form: {rest_txt}"
        else:
            subtext = f"Owned by {top['selected']:.0f}%. Also struggling: {rest_txt}"
        hero_color = ACCENT if hot else ALERT
    elif t == "injury_batch":
        injuries = story["injuries"]
        eyebrow = "INJURY ALERT"
        hero = f"{len(injuries)} UPDATE" + ("S" if len(injuries) != 1 else "")
        headline = "LATEST INJURY NEWS"
        names = [i["player"] for i in injuries]
        shown, extra = names[:12], names[12:]
        subtext = ", ".join(shown)
        if extra:
            subtext += f"  +{len(extra)} more -- full list in caption"
        hero_color = ALERT
    elif t == "deadline_reminder":
        eyebrow = "DEADLINE ALERT"
        hero = story["bucket"].upper()
        headline = f"GW{story['gw']} DEADLINE"
        subtext = "Lock in transfers and captain now."
        hero_color = WARN
        hashtags = f"{base_tags} #GW{story['gw']}"
    elif t == "gw_recap":
        eyebrow = f"GW{story['gw']} RECAP"
        hero = f"{story.get('highest_score', 'N/A')} PTS"
        headline = "TOP SCORE THIS GW"
        subtext = "Did your team beat it? Full breakdown in the caption."
        hero_color = ACCENT
        hashtags = f"{base_tags} #GW{story['gw']}"
    elif t == "kickoff":
        eyebrow = "KICK-OFF"
        hero = "LIVE"
        headline = f"{story['home']} vs {story['away']}"
        subtext = "Follow the FPL-relevant moments as they happen."
        hero_color = ACCENT
        hashtags = f"{base_tags} #{story['home']}v{story['away']}"
    elif t == "full_time":
        eyebrow = "FULL-TIME"
        hero = story["score"]
        headline = f"{story['home']} vs {story['away']}"
        subtext = "Full recap and bonus points once confirmed."
        minute_str = _minute_str(story)
        if minute_str:
            subtext = f"{minute_str}  |  {subtext}"
        hero_color = ACCENT
        hashtags = f"{base_tags} #{story['home']}v{story['away']}"
    elif t == "goal_update":
        eyebrow = "ASSIST CONFIRMED"
        hero = "GOAL!"
        headline = f"{story['player']} ({story['team']})"
        subtext = f"Assist: {story['assisted_by']}  |  {story['home']} {story['score']} {story['away']}"
        minute_str = _minute_str(story)
        if minute_str:
            subtext = f"{minute_str}  |  {subtext}"
        hero_color = ACCENT
        hashtags = f"{base_tags} #{story['team']}"
    elif t == "bonus_points":
        eyebrow = "BONUS POINTS"
        top = story["players"][0]
        hero = f"+{top['points']}"
        headline = f"{story['home']} {story['score']} {story['away']}"
        subtext = "  |  ".join(f"{p['name']} +{p['points']}" for p in story["players"])
        hero_color = ACCENT
        hashtags = f"{base_tags} #{story['home']}v{story['away']}"
    elif t in LIVE_EVENT_META:
        eyebrow, hero, hero_color = LIVE_EVENT_META[t]
        headline = f"{story['player']} ({story['team']})"
        subtext = f"{story['home']} {story['score']} {story['away']}"
        if t == "goal" and story.get("assisted_by"):
            subtext = f"Assist: {story['assisted_by']}  |  {subtext}"
        if t == "substitution" and story.get("subbed_out"):
            subtext = f"Off: {story['subbed_out']}  |  {subtext}"
        minute_str = _minute_str(story)
        if minute_str:
            subtext = f"{minute_str}  |  {subtext}"
        hashtags = f"{base_tags} #{story['team']}"
    else:
        eyebrow = "FPL NEWS"
        hero = "UPDATE"
        headline = story.get("player", "")
        subtext = None
        hero_color = ACCENT

    img = _hero_card(eyebrow, hero, headline, subtext, hero_color, hashtags)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


PRICE_RISE_HOOKS = [
    "Already own him, or bringing him in before he rises again?",
    "Time to cash in, or riding the wave?",
    "In your team yet, or watching from the sidelines?",
    "Bandwagon or already on board?",
    "Worth the extra spend, or overpriced now?",
]
PRICE_FALL_HOOKS = [
    "Panic sell or hold firm?",
    "Buying the dip, or steering clear?",
    "Time to cut losses, or backing him to bounce back?",
    "Selling up or staying loyal?",
    "Bargain now, or a reason to worry?",
]
STATUS_HOOKS = [
    "Does this wreck your GW plan?",
    "Time for a transfer, or riding it out?",
    "Bench him or bank on a late fitness call?",
    "How are you covering this one?",
    "Risk it, or play it safe this week?",
]
LOAN_HOOKS = [
    "Worth keeping an eye on, or off your radar now?",
    "Does this change how you're planning around him?",
    "Still fantasy relevant from his new club, or done for now?",
    "Surprised by this one, or saw it coming?",
]
TRANSFER_HOOKS = [
    "Did you see this one coming?",
    "Does this shake up your squad plans?",
    "Big move -- good business for the club, or a loss?",
    "How does this change the pecking order at his old club?",
]
DEPARTURE_HOOKS = [
    "End of an era, or overdue?",
    "Does this open a spot worth targeting?",
    "Will he be missed in FPL terms?",
]
SUSPENSION_HOOKS = [
    "Who's covering for him while he's out?",
    "Does this change your captaincy plans?",
    "Costly ban, or no big loss for his side?",
]

STATUS_CATEGORY_META = {
    # category -> (emoji, label prefix, hook list)
    "injury": ("\U0001F6A8", "INJURY ALERT", STATUS_HOOKS),
    "suspension": ("\U0001F7E5", "SUSPENDED", SUSPENSION_HOOKS),
    "loan": ("\U0001F504", "LOAN MOVE", LOAN_HOOKS),
    "transfer": ("\U0001F504", "TRANSFER NEWS", TRANSFER_HOOKS),
    "departure": ("\U0001F44B", "SQUAD NEWS", DEPARTURE_HOOKS),
    "availability": ("ℹ️", "AVAILABILITY UPDATE", STATUS_HOOKS),
}
DEADLINE_HOOKS = [
    "Transfers, captain, chip calls -- lock it in NOW.",
    "Last chance to make your move.",
    "Squad locked in, or still deciding?",
    "Don't get caught out -- set your team now.",
    "Final call on your captain -- who's it going to be?",
]
RECAP_HOOKS = [
    "Did YOU beat the top score?",
    "How does your squad compare?",
    "Gutted or buzzing with your GW?",
    "Beat it, matched it, or fell short?",
    "Where did that leave your rank?",
]
GOAL_HOOKS = [
    "Have him in your team?",
    "Nailed on captain material?",
    "Who's benefiting from that in FPL?",
    "Big green arrow incoming for whoever owns him.",
]
ASSIST_HOOKS = [
    "Quietly racking up the returns.",
    "Underrated FPL pick, or expected?",
    "Attacking returns keep coming for him.",
]
CARD_HOOKS = [
    "Does this change your captaincy call?",
    "Risk of a ban building here.",
    "Worth keeping an eye on for next week.",
]
RED_CARD_HOOKS = [
    "That's a missed fixture (or more) coming up.",
    "Big blow for their FPL assets this week.",
    "Does this change your transfer plans?",
]
PENALTY_MISS_HOOKS = [
    "Will he still be on penalties next time?",
    "Costly miss for anyone banking on the goal.",
    "Does this change the pen-taker pecking order?",
]
PENALTY_SAVE_HOOKS = [
    "Huge moment for his clean sheet odds.",
    "Goalkeeper picks looking good right now.",
    "That could be worth a green arrow for his owners.",
]
OWN_GOAL_HOOKS = [
    "Rough moment -- feel for him.",
    "Unlucky stat for anyone with him at the back.",
]
KICKOFF_HOOKS = [
    "Who are you backing for returns?",
    "Any of your players out there?",
    "Let's see what this one brings.",
]
FULL_TIME_HOOKS = [
    "How did your FPL assets do?",
    "Any big returns from this one?",
    "Bonus points still to be confirmed.",
]
SUBSTITUTION_HOOKS = [
    "Fresh legs -- could this pay off in FPL terms?",
    "Impact sub, or too little too late?",
    "Worth watching for a late returns.",
    "Does this open a chance for a start next week?",
]


FORM_HOT_HOOKS = [
    "Who's in your team? Who are you buying?",
    "Time to jump on one of them, or too late?",
    "Which of these are you backing to keep it going?",
    "Any of them in your squad yet?",
]
FORM_COLD_HOOKS = [
    "Hold, or sell before the next deadline?",
    "Do you trust any of them to bounce back?",
    "Who's getting binned first?",
    "How many of these are in your team?",
]

FOLLOW_ASKS = [
    "Follow for the next one.",
    "Follow @fantasycoachai so you don't miss the next update.",
    "Turn on notifications to catch these as they land.",
    "More like this on the feed -- give us a follow.",
    "Following along? Hit follow so you don't miss what's next.",
]


def build_caption(story):
    return f"{_build_caption_text(story)}\n\n{random.choice(FOLLOW_ASKS)}"


def _build_caption_text(story):
    t = story["type"]
    tags = _random_hashtags(3)

    if t == "price_change":
        if story["direction"] == "rise":
            hook = random.choice(PRICE_RISE_HOOKS)
            return (
                f"\U0001F4C8 {story['player']} ({story['team']}) is on the up -- now £{story['new_price_millions']}m.\n\n"
                f"{hook} {tags} #{story['team']}"
            )
        hook = random.choice(PRICE_FALL_HOOKS)
        return (
            f"\U0001F4C9 {story['player']} ({story['team']}) drops to £{story['new_price_millions']}m.\n\n"
            f"{hook} {tags} #{story['team']}"
        )
    if t == "price_changes":
        changes = story["changes"]
        rises = [c for c in changes if c["direction"] == "rise"]
        falls = [c for c in changes if c["direction"] == "fall"]
        # 🔻/🔺 are both literally "red triangle" in Unicode regardless of
        # direction -- no green/red distinction. Colored circles actually
        # differ by color: green for a rise, red for a fall.
        lines = [f"\U0001F534 {c['player']} ({c['team']}) -> £{c['new_price_millions']}m" for c in falls]
        lines += [f"\U0001F7E2 {c['player']} ({c['team']}) -> £{c['new_price_millions']}m" for c in rises]
        body = "\n".join(lines)
        return (
            f"\U0001F4CA PRICE CHANGES: {len(falls)} fall{'s' if len(falls) != 1 else ''}, "
            f"{len(rises)} rise{'s' if len(rises) != 1 else ''}.\n\n{body}\n\n"
            f"Winners and losers in your squad? {tags}"
        )
    if t == "status_change":
        category = story.get("category", "availability")
        emoji, label, hooks = STATUS_CATEGORY_META.get(category, STATUS_CATEGORY_META["availability"])
        hook = random.choice(hooks)
        return (
            f"{emoji} {label}: {story['player']} ({story['team']}) is {story['status']}.\n"
            f"\"{story['news']}\"\n\n"
            f"{hook} {tags}"
        )
    if t in ("form_hot", "form_cold"):
        hot = t == "form_hot"
        lines = []
        for n, p in enumerate(story["players"], 1):
            extra = f", owned by {p['selected']:.0f}%" if not hot else ""
            lines.append(f"{n}. {p['name']} ({p['team']}) - {p['form']:.1f} pts/game, £{p['price_millions']}m{extra}")
        body = "\n".join(lines)
        if hot:
            head = "\U0001F525 IN FORM: the players averaging the most points per game lately."
            hook = random.choice(FORM_HOT_HOOKS)
        else:
            head = "\U0001F976 STRUGGLING: popular picks who've stopped returning."
            hook = random.choice(FORM_COLD_HOOKS)
        return f"{head}\n\n{body}\n\n{hook} {tags}"
    if t == "injury_batch":
        injuries = story["injuries"]
        hook = random.choice(STATUS_HOOKS)
        lines = [f"\U0001F6A8 {i['player']} ({i['team']}) - {i['status']}: \"{i['news']}\"" for i in injuries]
        body = "\n".join(lines)
        return (
            f"\U0001F6A8 INJURY UPDATES ({len(injuries)}):\n\n{body}\n\n"
            f"{hook} {tags}"
        )
    if t == "deadline_reminder":
        hook = random.choice(DEADLINE_HOOKS)
        return (
            f"⏰ GW{story['gw']} deadline in {story['bucket']}! "
            f"{hook}\n\n{tags}"
        )
    if t == "gw_recap":
        hook = random.choice(RECAP_HOOKS)
        return (
            f"\U0001F525 GW{story['gw']} is in the books. Top score: {story.get('highest_score')} pts. "
            f"Most captained ID: {story.get('most_captained')}.\n\n"
            f"{hook} {tags}"
        )
    if t == "kickoff":
        hook = random.choice(KICKOFF_HOOKS)
        return f"⚽ KICK-OFF: {story['home']} vs {story['away']}.\n\n{hook} {tags}"
    if t == "full_time":
        hook = random.choice(FULL_TIME_HOOKS)
        minute_tag = f" ({_minute_str(story)})" if story.get("minute") is not None else ""
        return (
            f"\U0001F4CB FULL-TIME{minute_tag}: {story['home']} {story['score']} {story['away']}.\n\n"
            f"{hook} {tags}"
        )
    if t == "goal":
        hook = random.choice(GOAL_HOOKS)
        assist_line = f" Assisted by {story['assisted_by']}." if story.get("assisted_by") else ""
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"⚽ GOAL!{minute_tag} {story['player']} ({story['team']})!{assist_line} "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "goal_update":
        minute_tag = f" ({_minute_str(story)})" if story.get("minute") is not None else ""
        return (
            f"\U0001F4DD UPDATE{minute_tag}: {story['player']}'s goal ({story['team']}) was assisted by "
            f"{story['assisted_by']}! {story['home']} {story['score']} {story['away']}.\n\n{tags} #{story['team']}"
        )
    if t == "assist":
        hook = random.choice(ASSIST_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"\U0001F3AF ASSIST!{minute_tag} {story['player']} ({story['team']}) with the assist! "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "yellow_card":
        hook = random.choice(CARD_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"\U0001F7E8 YELLOW CARD!{minute_tag} {story['player']} ({story['team']}) is booked. "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "red_card":
        hook = random.choice(RED_CARD_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"\U0001F7E5 RED CARD!{minute_tag} {story['player']} ({story['team']}) is sent off! "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "penalty_miss":
        hook = random.choice(PENALTY_MISS_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"❌ PENALTY MISSED!{minute_tag} {story['player']} ({story['team']}) can't convert! "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "penalty_save":
        hook = random.choice(PENALTY_SAVE_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"\U0001F9E4 PENALTY SAVED!{minute_tag} {story['player']} ({story['team']}) with the stop! "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "own_goal":
        hook = random.choice(OWN_GOAL_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        return (
            f"\U0001F6A8 OWN GOAL!{minute_tag} {story['player']} ({story['team']}). "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
        )
    if t == "goal_disallowed":
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        what = "own goal" if story.get("was_own_goal") else "goal"
        return (
            f"❌ NO GOAL!{minute_tag} {story['player']}'s ({story['team']}) {what} has been ruled out. "
            f"Score corrected: {story['home']} {story['score']} {story['away']}.\n\n"
            f"Any FPL points from it are removed. {tags} #{story['team']}"
        )
    if t == "bonus_points":
        lines = ", ".join(f"{p['name']} +{p['points']}" for p in story["players"])
        return (
            f"\U0001F381 BONUS POINTS confirmed: {story['home']} {story['score']} {story['away']}.\n"
            f"{lines}.\n\n{tags} #{story['home']}v{story['away']}"
        )
    if t == "substitution":
        hook = random.choice(SUBSTITUTION_HOOKS)
        minute_tag = f" {_minute_str(story)}" if story.get("minute") is not None else ""
        off_line = f" Off: {story['subbed_out']}." if story.get("subbed_out") else ""
        return (
            f"\U0001F504 SUB!{minute_tag} {story['player']} ({story['team']}) is on.{off_line} "
            f"{story['home']} {story['score']} {story['away']}.\n\n{hook} {tags} #{story['team']}"
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

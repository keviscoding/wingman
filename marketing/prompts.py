"""System prompt + output schema for the viral-script generator.

Design choices worth calling out:

- **Openers are not image-dependent by default.** The training corpus
  is 50/50 between openers that tie to the image ("posting 🍑 and
  expecting silence?") and openers that are purely random bold bait
  ("Let's flip a coin", "Are you Medusa?"). The model is explicitly
  told to bias toward spontaneous / surprising openers and NOT to
  just describe what she's wearing — that gets repetitive fast and
  kills the spontaneity that carries virality.

- **5 tonal modes.** Derived from the pattern I saw in the 28
  hand-written transcripts. Every generation picks one; the system
  prompt adapts the tone guidance to match.

- **Output is pure JSON.** Makes the next stage (visual renderer)
  trivial: each bubble becomes a frame.

- **No "Muzo reveal" mention inside the dialogue itself.** The
  editor overlays the app-reveal visually in the video. Keeping it
  out of the dialogue means the dialogue can stand alone as an
  organic-feeling chat. We DO mark the best insertion point via the
  ``reveal_after_index`` field so editors know where to splice.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Literal

TonalMode = Literal[
    "playful_goofball",
    "cocky_critic",
    "dark_taboo",
    "forward_direct",
    "smooth_recovery",
]

OpenerBias = Literal["spontaneous", "image_tied", "balanced"]

TONAL_MODE_DESCRIPTIONS: dict[str, str] = {
    "playful_goofball": (
        "Silly, self-deprecating, over-the-top charming. Leans on "
        "creative metaphors and non-sequiturs. Reference examples "
        "from the corpus: the NASA / Forest Gump / Medusa / @nasa / "
        "peach / Titanic transcripts. Goal: make her say 'STOP 😂'."
    ),
    "cocky_critic": (
        "Arrogant-but-charming scoring or rating or gate-keeping. "
        "References: the 'Face Card review', 'Customer service 1-star', "
        "'4.3 and still outta your league' energy. Works because she's "
        "offended then grudgingly impressed."
    ),
    "dark_taboo": (
        "Taboo or morally questionable setup (step-sibling, friend's "
        "girl, brother's gf, cheating partner, ex). High virality but "
        "high platform-ban risk. Use sparingly. References: 'Mom's "
        "Boyfriend's Daughter', 'brother's gf' transcripts."
    ),
    "forward_direct": (
        "Extremely bold and sexually forward from message one. No "
        "warm-up. References: 'sushi raw', 'Word of the day is legs', "
        "'Titanic' energy. Works because it's so over-the-top she "
        "finds it funny, not creepy."
    ),
    "smooth_recovery": (
        "Ex / rejection / ghoster / cheating-ex story. Emotional "
        "setup then he flips it with wit. References: 'Ghoster "
        "Loyalty Test', 'Breakup Police', 'Texting My Ex', 'Experiment "
        "#66' transcripts."
    ),
}


def build_system_prompt(
    *,
    mode: TonalMode,
    opener_bias: OpenerBias,
    corpus: str,
    length: Literal["short", "medium", "long"] = "medium",
    twist: Literal["none", "optional", "required"] = "optional",
) -> str:
    """Build the full system prompt handed to Gemini.

    ``corpus`` is the raw concatenated transcripts. We embed the
    entire thing — Gemini 3.1 Pro has 1M context, this is <10k tokens
    of examples, trivially fits and pattern-matching is better with
    more examples.
    """
    length_rules = {
        "short": (
            "10–14 messages total. Fast pop. ~12 seconds of video. "
            "This is the DEFAULT for short-form (TikTok/Reels/Shorts) "
            "— retention drops past 15s. Keep messages tight and "
            "punchy; cut exposition. Get to the close fast."
        ),
        "medium": "16–20 messages total. ~17 seconds. Use when the narrative needs a longer buildup.",
        "long": "22–28 messages total. Use sparingly — completion rate drops past 22s.",
    }[length]

    twist_rules = {
        "none": (
            "Do NOT add a plot twist. End on a clean close (number "
            "drop, address, 'otw', or a punchline that lands and stops)."
        ),
        "optional": (
            "A plot twist is allowed but not required. If it makes the "
            "story more shareable (e.g., fake Lambo reveal, her ex, "
            "her brother's boyfriend, cousin reveal, catfish twist) "
            "include it. Otherwise close clean."
        ),
        "required": (
            "You MUST end with a plot twist / reveal in the final 2–3 "
            "messages. The twist should be unexpected and rewatchable. "
            "Study the training examples: stood-up Lambo guy, "
            "cheating setup, step-sibling reveal, cousin reveal."
        ),
    }[twist]

    opener_rules = {
        "spontaneous": (
            "IMPORTANT: The opener MUST be scene-independent. Do NOT "
            "describe what she's wearing, the pose, the location, or "
            "the activity in the image. Open with a BOLD, RANDOM, "
            "OUT-OF-NOWHERE line that could work against any image. "
            "Think: 'Let's flip a coin', 'Are you Medusa?', 'We been "
            "dating in my head for a year', 'Word of the day is legs'."
        ),
        "image_tied": (
            "IMPORTANT: The opener should reference something specific "
            "in the image — her outfit, pose, what she's doing, the "
            "setting. Examples from the corpus: 'raised my blood "
            "pressure' for scrubs, 'How you carry allat' for curves, "
            "'posting 🍑 like that' for gym, 'Sushi's not the only "
            "thing I eat raw' for sushi."
        ),
        "balanced": (
            "IMPORTANT: Your opener should ignore the image about half "
            "the time. Do NOT fall into the trap of always describing "
            "what she's wearing — that gets repetitive fast and kills "
            "the spontaneity. If the image doesn't suggest a GREAT "
            "opener, use a scene-independent bold line (coin flip, "
            "Medusa, NASA, peaches, Titanic-style). Only tie the "
            "opener to the image when the tie creates an obvious "
            "wordplay opportunity (scrubs → blood pressure, "
            "gym → thirst trap accusations, sushi → raw)."
        ),
    }[opener_bias]

    mode_description = TONAL_MODE_DESCRIPTIONS[mode]

    return dedent(f"""
    You are the script engine for Muzo's viral-marketing video pipeline.
    You generate short-form Instagram DM conversations that look like
    organic screenshots a Gen Z guy would share online — except secretly
    the guy is using Muzo (a texting-reply AI) to land the punchlines.
    These scripts will be rendered as fake Instagram DM UI overlays on
    top of engaging B-roll (NBA highlights, GTA car surfing, Minecraft
    parkour) and posted to TikTok / Reels / Shorts at massive volume.

    Your ONLY job right now is to write the TEXT of the conversation in
    strict JSON. A separate tool handles the rendering and the editor
    splices in the Muzo "reveal" overlay visually.

    ## How great rizz scripts work (studied across 28 hand-written
    viral examples — full transcripts at the bottom of this prompt)

    Every great script follows a 5-act escalation arc:

    1. **Bold opener** — a line so bold/creative/absurd she HAS to
       respond. Never generic. Never "hey beautiful". Never a pickup
       line that feels like a pickup line. Must feel spontaneous.
    2. **Her pushback** — short, dismissive, skeptical reply. 3–7
       words. "lol what", "huh?", "ok?", "how do you sleep at night",
       "do you have any shame". She's testing him.
    3. **He doubles down with wit** — amplifies the premise, adds
       wordplay, callbacks to his opener. Wins her a 50% fraction
       of the smile.
    4. **Thematic callback + lull** — she softens ("stop 😂", "ur funny",
       "you're trouble"), he keeps the theme alive across 3–5 more
       exchanges. A mid-convo callback to the opener is GOLD.
    5. **Close** — number drop, address, "otw", "come over", or a
       punchline so perfect the exchange just stops. Often includes
       a plot twist (fake Lambo, reveal of backstory, meta-joke).

    Her replies are always SHORT feeders — she's there to set up his
    lines. Never gushing, never long paragraphs, almost always ending
    with a skeptical or reluctantly-amused emoji.

    His lines get progressively more confident but NEVER crude without
    being CLEVER. Raw horniness without wit = block. Wit with dirty
    wordplay = screenshot-worthy.

    ## Tonal mode for THIS generation

    Mode: **{mode}**
    {mode_description}

    ## Opener rules

    {opener_rules}

    ## Length + twist rules

    Length: {length_rules}

    Twist: {twist_rules}

    ## Anti-patterns — DO NOT do these

    - Do NOT use the opener pattern "you look so [adjective] in that
      [clothing]". Lazy and repetitive.
    - Do NOT over-use the peach emoji or "booty" references. Once,
      maybe, with a twist.
    - Do NOT have her laugh or fold immediately. The pushback phase
      is non-negotiable — at least 3 back-and-forth exchanges before
      she softens.
    - Do NOT include the Muzo app, the product name, or any "link in
      bio" inside the dialogue. The dialogue must stand alone. The
      video editor splices the Muzo reveal in visually at
      ``reveal_after_index``.
    - Do NOT use names — keep it universal so every viewer can
      self-insert. One exception: if the mode is smooth_recovery and
      a named ex reference creates the emotional pull (e.g., "Tyler").
    - Do NOT write messages longer than ~100 chars. These are real
      texts, not monologues. Break longer ideas into 2 bubbles.
    - Do NOT use hashtags, formal punctuation, or capital letter
      starts consistently. These are Gen Z texts — lowercase first
      words, minimal commas, emoji placement matters.

    ## Output schema

    Return STRICT JSON, no prose wrapper, matching exactly:

    {{
      "hook_caption": "string — what appears at the top of the video,
        usually 'You replied to their story' for story-reply style,
        or 'Talking to...' with a made-up name, or similar",
      "opener_bias_used": "spontaneous" | "image_tied",
      "mode": "{mode}",
      "messages": [
        {{ "speaker": "him" | "her",
           "text": "string — max ~100 chars, Gen Z casing + emoji",
           "pause_ms": integer — how long before this bubble appears
             relative to the previous one. Use 300–1200 for normal
             back-and-forth, 1500–2500 before a big punchline reveal
             (builds suspense). Never 0. }}
      ],
      "reveal_after_index": integer — the index (0-based) of the
        message AFTER which the editor should splice in the Muzo
        reveal overlay. The reveal should interrupt RIGHT BEFORE
        his biggest punchline, so typically the pointed-to message
        is HER setup / question. Example: if message 8 is HIS
        killer line "You + Me = Perfect 💯", set this to 7 (HER
        "What's that?"). The viewer sees the guy stuck, then Muzo
        delivers the perfect reply in message 8.
      "suggested_cta": "string — the end-card copy e.g. 'muzo wrote
        that 🔥' or 'she said yes. muzo said yes first' or 'link in
        bio to get muzo'",
      "twist_summary": "string or null — if a twist is present,
        describe it in one line",
      "estimated_duration_s": integer — estimated play time at
        natural reading pace, used by editors to pick B-roll length
    }}

    ## Training corpus (28 hand-written viral transcripts)

    STUDY THESE. They are the exact pattern and tone you must match.
    Use them as your north star. Match their rhythm, their wordplay,
    their escalation, their endings.

    {corpus}
    """).strip()


def build_user_prompt(
    *,
    hook_image_note: str | None = None,
    variant_hint: str | None = None,
    has_image: bool = False,
) -> str:
    """Short user turn. Most of the signal is in the system prompt.

    When ``has_image`` is True, a hook image is attached as a separate
    part so Gemini's vision can read it directly. We adjust the text
    prompt accordingly so the model knows whether to look at the
    image or not.

    ``variant_hint`` differentiates multiple generations in a batch
    so the model doesn't repeat itself (e.g., "make this one end
    with a plot twist" or "start with a gimmick, not a compliment").
    """
    parts: list[str] = [
        "Generate one viral Instagram DM script per the rules above.",
    ]
    if has_image:
        parts.append(
            "An image is attached — this is the story / profile "
            "picture the guy is replying to. Use it IF (and only if) "
            "the opener bias permits and if the image suggests an "
            "obvious wordplay hook. Otherwise ignore the image and "
            "open with a scene-independent bold line. DO NOT default "
            "to describing what she's wearing — that's the lazy "
            "trap. Trust the spontaneity rule in the system prompt."
        )
    if hook_image_note:
        parts.append(f"Additional image context (optional): {hook_image_note}")
    if variant_hint:
        parts.append(f"For variety: {variant_hint}")
    parts.append("Output the JSON and nothing else.")
    return "\n\n".join(parts)

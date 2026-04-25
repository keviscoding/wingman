// ChatDetailScreen — REPLIES section + CONVERSATION section.

function ChatDetailScreen({ chat, onBack, onOpenPaywall }) {
  const [extra, setExtra] = React.useState('');
  const [extraOpen, setExtraOpen] = React.useState(false);
  const [regenerating, setRegenerating] = React.useState(false);

  const onRegen = () => {
    setRegenerating(true);
    setTimeout(() => setRegenerating(false), 1800);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar leftLabel="Back" leftAction={onBack} title={chat?.name || 'Amy'} />
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 16px 32px', display: 'flex', flexDirection: 'column', gap: 20 }}>

        {/* REPLIES SECTION */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px' }}>
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: W.fgDim }}>REPLIES</span>
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: W.fgDimmer }}>5 OPTIONS</span>
          </div>

          <ReplyCard angle="BOLD"     text="Sounds like a busy week — earn it. Friday, 8pm, my place. Wine's on me." why="frame challenge — punishes her flake" />
          <ReplyCard angle="PLAYFUL"  text="Busy is a personality trait now? Bold of you. Tell me one good thing." why="match her energy, raise the stakes" />
          <ReplyCard angle="SEXUAL"   text="Sleeping under the stars? You're trouble. I want details over dinner." why="callback + escalation" />
          <ReplyCard angle="SINCERE"  text="That sounds incredible. What was the moment you'll remember most?" why="invite a real story, build rapport" />
          <ReplyCard angle="CURIOUS"  text="Wait — alone, or who dragged you out there?" why="lightweight probe, opens a thread" />

          <div style={{ background: W.surface2, borderRadius: 12, padding: 14, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontSize: 14, color: W.fg, lineHeight: 1.4 }}><span style={{ color: W.fgDim, fontWeight: 700 }}>Read:</span> she's testing your investment by playing busy</div>
            <div style={{ fontSize: 14, color: W.fg, lineHeight: 1.4 }}><span style={{ color: W.fgDim, fontWeight: 700 }}>Move:</span> takeaway, then ping in 48h</div>
          </div>

          <Pressable onClick={() => setExtraOpen(o => !o)} as="div" style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px', borderRadius: 10, background: W.surface, border: `1px solid ${W.border}`,
          }}>
            <span style={{ fontSize: 14, color: W.fgDim, fontWeight: 600 }}>+ Add extra context</span>
            <span style={{ color: W.fgDimmer, fontSize: 12 }}>{extraOpen ? 'Close' : 'Optional'}</span>
          </Pressable>
          {extraOpen && (
            <textarea
              value={extra}
              onChange={e => setExtra(e.target.value)}
              placeholder="e.g. she just got back from a trip"
              style={{
                width: '100%', minHeight: 80, padding: 12,
                background: W.surface, border: `1px solid ${W.border}`, borderRadius: 10,
                color: W.fg, fontSize: 15, fontFamily: W.font, resize: 'vertical', outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          )}

          <PrimaryButton onClick={onRegen} disabled={regenerating}>
            {regenerating ? <><Spinner size={16} color="#0a0a0f" /> Generating fresh replies…</> : 'Regenerate replies'}
          </PrimaryButton>
        </div>

        {/* CONVERSATION SECTION */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ padding: '0 4px' }}>
            <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: W.fgDim }}>CONVERSATION · 8 MSGS</span>
          </div>
          <div style={{ background: W.surface, border: `1px solid ${W.border}`, borderRadius: 16, padding: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Bubble side="them">hey, sorry — crazy week 😅</Bubble>
            <Bubble side="them">just got back from this insane trip</Bubble>
            <Bubble side="me">no apology needed. tell me one good thing</Bubble>
            <Bubble side="them">honestly? slept under the stars on a beach</Bubble>
            <Bubble side="them">didn't see my phone for 3 days</Bubble>
            <Bubble side="me">that sounds incredible. you alone?</Bubble>
            <Bubble side="them">old uni friends, kind of impulsive</Bubble>
            <Bubble side="them">how was your week?</Bubble>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({ side, children }) {
  const me = side === 'me';
  return (
    <div style={{
      maxWidth: '85%', alignSelf: me ? 'flex-end' : 'flex-start',
      padding: '8px 12px', borderRadius: 18,
      borderBottomRightRadius: me ? 6 : 18,
      borderBottomLeftRadius: me ? 18 : 6,
      background: me ? 'rgba(102,224,180,0.18)' : W.surface2,
      color: me ? W.accent : W.fg,
      fontSize: 15, lineHeight: 1.4,
    }}>{children}</div>
  );
}

window.ChatDetailScreen = ChatDetailScreen;

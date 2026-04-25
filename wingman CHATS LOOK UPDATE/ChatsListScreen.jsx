// ChatsListScreen — list of saved chats. Has empty state.

// Deterministic warm-tinted hue from a name string — so monograms feel personal
// without us inventing colors per row. Stays in oklch space, low chroma, dark.
function nameTint(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  return {
    bg: `oklch(0.32 0.06 ${hue})`,
    fg: `oklch(0.92 0.04 ${hue})`,
    ring: `oklch(0.45 0.08 ${hue} / 0.5)`,
  };
}

function initials(name) {
  // Strip parenthetical source like "(Hinge)" before deriving initials
  const clean = name.replace(/\(.*?\)/g, '').trim();
  const parts = clean.split(/\s+/).slice(0, 2);
  return parts.map(p => p[0]).join('').toUpperCase();
}

// Tiny source glyphs — drawn as small SVG marks (not real logos, evocative)
function SourceGlyph({ source, size = 10 }) {
  const c = '#9494a3';
  if (source === 'hinge')   return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><path d="M3 2v8h1.6V6.6h2.8V10H9V2H7.4v3.1H4.6V2z"/></svg>;
  if (source === 'tinder')  return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><path d="M6 1.2C5.4 2.6 4 3.4 4 5.5c0 1.2.4 2 .9 2.5C4.4 7.5 4.2 7 4.2 6.4c0-1.5 1.2-2.6 1.8-3.6.4 1 1.8 1.8 1.8 3.6 0 1.5-1 2.7-2.4 2.8C5 9.4 5.4 9.6 6 9.6c1.7 0 3-1.4 3-3.4 0-2.6-2-3.6-3-5z"/></svg>;
  if (source === 'bumble')  return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><path d="M2.5 4l3-2.4 3 2.4v4L5.5 10.4 2.5 8z"/></svg>;
  if (source === 'imessage')return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><path d="M6 1.5C3.2 1.5 1 3.4 1 5.7c0 1.4.8 2.7 2.1 3.4L2.5 11l2.2-1.1c.4.1.8.1 1.3.1 2.8 0 5-1.9 5-4.3S8.8 1.5 6 1.5z"/></svg>;
  if (source === 'whatsapp')return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><path d="M6 1.5a4.5 4.5 0 0 0-3.9 6.7L1.5 10.5l2.4-.5A4.5 4.5 0 1 0 6 1.5zm2.4 6.2c-.1.3-.6.6-.9.6-.2 0-.5 0-1.5-.4-1.3-.5-2.1-1.8-2.1-1.9-.1-.1-.5-.7-.5-1.3 0-.7.3-1 .5-1.1.1-.1.3-.2.4-.2h.3c.1 0 .2 0 .3.2.1.2.3.7.4.8 0 .1.1.2 0 .3l-.1.2-.2.2c-.1.1-.2.2-.1.3.1.2.4.6.8.9.5.4.9.6 1.1.6.1 0 .2 0 .3-.1.1-.1.3-.4.4-.5.1-.1.2-.1.3 0 .1 0 .8.4.9.4l.2.1c0 .1 0 .4-.1.6z"/></svg>;
  return <svg width={size} height={size} viewBox="0 0 12 12" fill={c}><circle cx="6" cy="6" r="2.5"/></svg>;
}

const SOURCE_LABEL = {
  hinge: 'Hinge', tinder: 'Tinder', bumble: 'Bumble',
  imessage: 'iMessage', whatsapp: 'WhatsApp', dm: 'IG DM',
};

function ChatsListScreen({ onBack, onOpenChat, empty = false }) {
  const chats = empty ? [] : [
    { id: 1, name: 'Amy',     source: 'hinge',    preview: "sounds like you've been busy — tell me one thing…", outgoing: true,  msgs: 12, when: 'just now',     mins: 2,    hasReplies: true,  unread: 0, angle: 'BOLD' },
    { id: 2, name: 'Maya',    source: 'imessage', preview: 'haha okay you got me, that was good',                outgoing: false, msgs: 8,  when: '2h ago',        mins: 120,  hasReplies: true,  unread: 2, angle: 'PLAYFUL' },
    { id: 3, name: 'Sophie',  source: 'bumble',   preview: "what's the most spontaneous thing you've done?",     outgoing: true,  msgs: 4,  when: 'yesterday',     mins: 1500, hasReplies: false, unread: 0 },
    { id: 4, name: 'Lina',    source: 'whatsapp', preview: 'sorry just saw this',                                 outgoing: false, msgs: 22, when: '2d ago',        mins: 2880, hasReplies: true,  unread: 1, angle: 'SINCERE' },
    { id: 5, name: 'Jess',    source: 'hinge',    preview: 'pick one — Tokyo or Lisbon, no hesitation',           outgoing: true,  msgs: 6,  when: '4d ago',        mins: 5760, hasReplies: false },
    { id: 6, name: 'Priya',   source: 'tinder',   preview: 'omg the ramen pic, where is that',                    outgoing: false, msgs: 14, when: '1w ago',        mins: 10080, hasReplies: true,  unread: 0, angle: 'CURIOUS' },
    { id: 7, name: 'Kate D.', source: 'dm',       preview: 'we should rain-check',                                outgoing: false, msgs: 9,  when: '2w ago',        mins: 20160, hasReplies: false },
  ];

  // Bucket by recency
  const today = chats.filter(c => c.mins < 1440);
  const week  = chats.filter(c => c.mins >= 1440 && c.mins < 10080);
  const older = chats.filter(c => c.mins >= 10080);

  const totalUnread = chats.reduce((n, c) => n + (c.unread || 0), 0);

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        leftLabel="Back" leftAction={onBack}
        title="Your chats"
        right={!empty && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {totalUnread > 0 && (
              <span style={{
                fontSize: 11, fontWeight: 700, letterSpacing: '0.04em',
                padding: '3px 7px', borderRadius: 999,
                background: W.accent, color: W.bg, lineHeight: 1,
              }}>{totalUnread} new</span>
            )}
            <span style={{ color: W.fgDim, fontSize: 13, fontWeight: 600 }}>{chats.length}</span>
          </div>
        )}
      />

      {empty ? (
        <EmptyChats onBack={onBack} />
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', paddingBottom: 24 }}>
          {/* Search */}
          <div style={{ padding: '12px 16px 4px' }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px', borderRadius: 12,
              background: W.surface, border: `1px solid ${W.border}`,
            }}>
              <SearchIcon />
              <span style={{ flex: 1, color: W.fgDimmer, fontSize: 15 }}>Search names or chats</span>
              <span style={{
                color: W.fgDimmer, fontSize: 11, fontWeight: 600,
                padding: '2px 6px', border: `1px solid ${W.border}`, borderRadius: 4,
              }}>⌘K</span>
            </div>
          </div>

          {today.length > 0 && <ChatGroup label="Today"             chats={today} onOpenChat={onOpenChat} />}
          {week.length  > 0 && <ChatGroup label="Earlier this week" chats={week}  onOpenChat={onOpenChat} />}
          {older.length > 0 && <ChatGroup label="Older"             chats={older} onOpenChat={onOpenChat} />}
        </div>
      )}
    </div>
  );
}

function ChatGroup({ label, chats, onOpenChat }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{
        padding: '8px 22px 6px',
        fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
        color: W.fgDim, textTransform: 'uppercase',
      }}>{label}</div>
      <div style={{
        margin: '0 16px',
        background: W.surface,
        border: `1px solid ${W.border}`,
        borderRadius: 16, overflow: 'hidden',
      }}>
        {chats.map((c, i) => (
          <ChatRow key={c.id} chat={c} isLast={i === chats.length - 1} onOpenChat={onOpenChat} />
        ))}
      </div>
    </div>
  );
}

function ChatRow({ chat, isLast, onOpenChat }) {
  const tint = nameTint(chat.name);
  const angleColor = chat.angle ? W.angle[chat.angle] : null;
  return (
    <Pressable onClick={() => onOpenChat && onOpenChat(chat)} as="div" style={{
      padding: '14px 14px',
      borderBottom: isLast ? 'none' : `1px solid ${W.border}`,
      display: 'flex', gap: 12, alignItems: 'center', textAlign: 'left',
      position: 'relative',
    }}>
      {/* Avatar */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <div style={{
          width: 44, height: 44, borderRadius: '50%',
          background: tint.bg,
          color: tint.fg,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em',
        }}>{initials(chat.name)}</div>
        {/* Replies-ready ring */}
        {chat.hasReplies && (
          <div style={{
            position: 'absolute', inset: -3, borderRadius: '50%',
            border: `1.5px solid ${W.accent}`,
            opacity: 0.55, pointerEvents: 'none',
          }} />
        )}
        {/* Unread badge */}
        {chat.unread > 0 && (
          <div style={{
            position: 'absolute', top: -2, right: -2,
            minWidth: 18, height: 18, padding: '0 5px', borderRadius: 9,
            background: W.accent, color: W.bg,
            fontSize: 11, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: `2px solid ${W.surface}`,
          }}>{chat.unread}</div>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: W.fg, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{chat.name}</span>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              fontSize: 11, fontWeight: 600, color: W.fgDim,
              padding: '2px 6px', borderRadius: 6,
              background: W.surface2, border: `1px solid ${W.border}`,
              flexShrink: 0,
            }}>
              <SourceGlyph source={chat.source} />
              {SOURCE_LABEL[chat.source]}
            </span>
          </div>
          <span style={{ color: W.fgDimmer, fontSize: 12, fontWeight: 500, flexShrink: 0 }}>{chat.when}</span>
        </div>

        <div style={{
          color: chat.unread > 0 ? W.fg : W.fgDim,
          fontSize: 14, lineHeight: 1.35,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: chat.unread > 0 ? 500 : 400,
        }}>
          {chat.outgoing && <span style={{ color: W.fgDimmer, fontWeight: 600 }}>You: </span>}
          {chat.preview}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
          <span style={{ color: W.fgDimmer, fontSize: 12, fontWeight: 500 }}>{chat.msgs} msgs</span>
          {chat.hasReplies && angleColor && (
            <>
              <span style={{ color: W.fgDimmer }}>·</span>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 5,
                fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                color: angleColor,
              }}>
                <span style={{ width: 5, height: 5, borderRadius: 3, background: angleColor }} />
                {chat.angle}
              </span>
              <span style={{ color: W.fgDimmer, fontSize: 11 }}>last copied</span>
            </>
          )}
          {chat.hasReplies && !angleColor && (
            <>
              <span style={{ color: W.fgDimmer }}>·</span>
              <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                color: W.accent,
              }}>5 REPLIES READY</span>
            </>
          )}
        </div>
      </div>
    </Pressable>
  );
}

function EmptyChats({ onBack }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: 32, gap: 24, textAlign: 'center',
      backgroundImage: 'radial-gradient(70% 40% at 50% 30%, rgba(102,224,180,0.06), transparent 70%)',
    }}>
      <ChatsIllustration />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 280 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Nothing here yet</h2>
        <p style={{ color: W.fgDim, fontSize: 15, margin: 0, lineHeight: 1.4 }}>Capture a chat — Wingman saves the conversation and your replies for later.</p>
      </div>
      <div style={{ width: '100%', maxWidth: 320 }}>
        <PrimaryButton onClick={onBack}>Capture a chat</PrimaryButton>
      </div>
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={W.fgDim} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function ChatsIllustration() {
  return (
    <svg width="124" height="124" viewBox="0 0 160 160" fill="none">
      {/* Phone */}
      <rect x="42" y="22" width="76" height="116" rx="14" stroke={W.border} strokeWidth="1.5" />
      {/* Bubbles inside phone */}
      <rect x="52" y="48" width="42" height="14" rx="7" fill={W.surface2} />
      <rect x="60" y="68" width="50" height="14" rx="7" fill="rgba(102,224,180,0.18)" />
      <rect x="52" y="88" width="36" height="14" rx="7" fill={W.surface2} />
      <rect x="60" y="108" width="46" height="14" rx="7" fill="rgba(102,224,180,0.18)" />
      {/* Sparkle (mint) */}
      <g transform="translate(122 30)" stroke={W.accent} strokeWidth="1.5" strokeLinecap="round">
        <path d="M0 -8 V8" />
        <path d="M-8 0 H8" />
        <path d="M-5.5 -5.5 L5.5 5.5" opacity="0.5" />
        <path d="M5.5 -5.5 L-5.5 5.5" opacity="0.5" />
      </g>
    </svg>
  );
}

window.ChatsListScreen = ChatsListScreen;

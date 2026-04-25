// HomeScreen — the primary screen. 5 distinct states.
// state: 'permission_needed' | 'ready' | 'generating' | 'result' | 'error'

// Recent chats — used by both the avatar pill (TopBar) and the rail (under TopBar)
const RECENT_CHATS = [
  { id: 1, name: 'Amy',    source: 'hinge',    preview: "tell me one thing…",          when: '2h',   hasReplies: true,  unread: 0 },
  { id: 2, name: 'Maya',   source: 'imessage', preview: 'haha okay you got me',        when: '5h',   hasReplies: true,  unread: 2 },
  { id: 3, name: 'Sophie', source: 'bumble',   preview: "Tokyo or Lisbon?",            when: '1d',   hasReplies: false, unread: 0 },
  { id: 4, name: 'Lina',   source: 'whatsapp', preview: 'sorry just saw this',         when: '2d',   hasReplies: true,  unread: 1 },
];

// Tiny deterministic tint — duplicated here from ChatsListScreen so this file stays self-contained.
function homeTint(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  return { bg: `oklch(0.32 0.06 ${hue})`, fg: `oklch(0.92 0.04 ${hue})` };
}
function homeInitials(name) {
  const clean = name.replace(/\(.*?\)/g, '').trim();
  return clean.split(/\s+/).slice(0, 2).map(p => p[0]).join('').toUpperCase();
}

// ─────────────────────────────────────────────────────────────
// Avatar-stack pill — replaces the "Chats" text link in TopBar
// ─────────────────────────────────────────────────────────────
function ChatsPill({ onOpenChats, chats = RECENT_CHATS }) {
  const stack = chats.slice(0, 3);
  const hasUnread = chats.some(c => c.unread > 0);
  return (
    <Pressable onClick={onOpenChats} style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      padding: '4px 10px 4px 4px', borderRadius: 999,
      background: W.surface2, border: `1px solid ${W.border}`,
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        {stack.map((c, i) => {
          const t = homeTint(c.name);
          return (
            <div key={c.id} style={{
              width: 24, height: 24, borderRadius: '50%',
              background: t.bg, color: t.fg,
              fontSize: 10, fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: `2px solid ${W.surface}`,
              marginLeft: i === 0 ? 0 : -8,
              zIndex: stack.length - i,
            }}>{homeInitials(c.name)}</div>
          );
        })}
      </div>
      <span style={{ color: W.fg, fontSize: 13, fontWeight: 600 }}>Chats</span>
      {hasUnread && (
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: W.accent,
          boxShadow: `0 0 0 2px ${W.surface2}`,
          position: 'absolute', top: 4, right: 8,
        }} />
      )}
    </Pressable>
  );
}

// ─────────────────────────────────────────────────────────────
// Horizontal "Recent" rail — sits under TopBar on idle states
// ─────────────────────────────────────────────────────────────
function RecentRail({ onOpenChats }) {
  return (
    <div style={{ paddingTop: 14, paddingBottom: 6 }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        padding: '0 20px 10px',
      }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.1em',
          color: W.fgDim, textTransform: 'uppercase',
        }}>Recent chats</span>
        <Pressable onClick={onOpenChats} as="span" style={{
          color: W.accent, fontSize: 12, fontWeight: 600,
        }}>See all →</Pressable>
      </div>
      <div style={{
        display: 'flex', gap: 10, padding: '0 16px 4px',
        overflowX: 'auto', WebkitOverflowScrolling: 'touch',
        scrollbarWidth: 'none',
      }}>
        {RECENT_CHATS.map(c => <RecentCard key={c.id} chat={c} onOpenChats={onOpenChats} />)}
        <Pressable onClick={onOpenChats} as="div" style={{
          flexShrink: 0, width: 92, height: 116,
          borderRadius: 14, border: `1.5px dashed ${W.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: W.fgDim, fontSize: 12, fontWeight: 600, textAlign: 'center',
          padding: 8, lineHeight: 1.3,
        }}>View all<br/>chats</Pressable>
      </div>
    </div>
  );
}

function RecentCard({ chat, onOpenChats }) {
  const t = homeTint(chat.name);
  return (
    <Pressable onClick={onOpenChats} as="div" style={{
      flexShrink: 0, width: 124, height: 116,
      borderRadius: 14, padding: 12,
      background: W.surface, border: `1px solid ${W.border}`,
      display: 'flex', flexDirection: 'column', gap: 8,
      position: 'relative', textAlign: 'left',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ position: 'relative' }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            background: t.bg, color: t.fg, fontSize: 11, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>{homeInitials(chat.name)}</div>
          {chat.hasReplies && (
            <div style={{
              position: 'absolute', inset: -2, borderRadius: '50%',
              border: `1.5px solid ${W.accent}`, opacity: 0.55,
            }} />
          )}
        </div>
        <span style={{ color: W.fgDimmer, fontSize: 11, fontWeight: 500 }}>{chat.when}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minHeight: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: W.fg, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{chat.name}</div>
        <div style={{
          fontSize: 12, color: W.fgDim, lineHeight: 1.3,
          overflow: 'hidden', display: '-webkit-box',
          WebkitBoxOrient: 'vertical', WebkitLineClamp: 2,
        }}>{chat.preview}</div>
      </div>
      {chat.unread > 0 && (
        <div style={{
          position: 'absolute', top: 8, right: 8,
          minWidth: 16, height: 16, padding: '0 4px', borderRadius: 8,
          background: W.accent, color: W.bg,
          fontSize: 10, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{chat.unread}</div>
      )}
    </Pressable>
  );
}

function HomeScreen({ state, onChangeState, onOpenChats, onOpenPaywall }) {
  const showRail = state === 'permission_needed' || state === 'ready' || state === 'error';
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota={state === 'result' ? 'Pro · 12/200' : 'Free · 7 left'}
        right={
          <>
            <ChatsPill onOpenChats={onOpenChats} />
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      {state === 'generating' && <LoadingBanner />}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {showRail && <RecentRail onOpenChats={onOpenChats} />}
        {state === 'permission_needed' && <PermissionView onPick={() => onChangeState('ready')} />}
        {state === 'ready' && <ReadyView onGenerate={() => onChangeState('generating')} />}
        {state === 'generating' && <GeneratingView />}
        {state === 'result' && <ResultView onAdd={() => onChangeState('ready')} onRegen={() => onChangeState('generating')} onOpenPaywall={onOpenPaywall} />}
        {state === 'error' && <ErrorView onRetry={() => onChangeState('generating')} />}
      </div>
    </div>
  );
}

function PermissionView({ onPick }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '36px 24px 32px', gap: 22 }}>
      <PhoneIllustration />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 300 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Take a screenshot of any chat</h1>
        <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>Wingman reads it instantly and writes 5 perfect replies.</p>
      </div>
      <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 14, marginTop: 4 }}>
        <PrimaryButton onClick={onPick}>Pick a screenshot</PrimaryButton>
        <div style={{ textAlign: 'center' }}>
          <TextLink>↻ Try auto-detect again</TextLink>
        </div>
      </div>
    </div>
  );
}

function ReadyView({ onGenerate }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '20px 24px 32px', gap: 16 }}>
      <Thumbnail active />
      <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ color: W.fg, fontSize: 15, fontWeight: 600 }}>Just now</div>
        <div style={{ color: W.fgDimmer, fontSize: 13 }}>From your library</div>
      </div>
      <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
        <PrimaryButton onClick={onGenerate}>Generate replies <span style={{ fontSize: 18 }}>→</span></PrimaryButton>
        <div style={{ textAlign: 'center' }}>
          <TextLink>Pick a different screenshot</TextLink>
        </div>
      </div>
    </div>
  );
}

function GeneratingView() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '32px 24px', gap: 20 }}>
      <div style={{ position: 'relative' }}>
        <Thumbnail dim />
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spinner size={36} />
        </div>
      </div>
      <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ color: W.fg, fontSize: 17, fontWeight: 700 }}>Crafting your replies</div>
        <div style={{ color: W.fgDim, fontSize: 13, maxWidth: 280, lineHeight: 1.4 }}>Reading the conversation, picking the move, writing options…</div>
      </div>
    </div>
  );
}

function ResultView({ onAdd, onRegen, onOpenPaywall }) {
  return (
    <div style={{ position: 'relative', padding: '20px 16px 100px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 4px 4px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Amy</div>
          <Pressable as="span" style={{ color: W.accent, fontSize: 13, fontWeight: 600, opacity: 0.85, display: 'inline-flex' }}>Saved to your chats →</Pressable>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Pressable onClick={onRegen} style={{ width: 36, height: 36, borderRadius: 10, background: W.surface, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
            <Icon name="refresh" size={16} />
          </Pressable>
          <Pressable onClick={onAdd} style={{ width: 36, height: 36, borderRadius: 10, background: W.surface, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
            <Icon name="plus" size={16} />
          </Pressable>
        </div>
      </div>

      <ReplyCard angle="BOLD"     text="Sounds like a busy week — earn it. Friday, 8pm, my place. Wine's on me." why="frame challenge — punishes her flake" />
      <ReplyCard angle="PLAYFUL"  text="Busy is a personality trait now? Bold of you. Tell me one good thing." why="match her energy, raise the stakes" />
      <ReplyCard angle="SEXUAL"   text="Sleeping under the stars? You're trouble. I want details over dinner." why="callback + escalation" />
      <ReplyCard angle="SINCERE"  text="That sounds incredible. What was the moment you'll remember most?" why="invite a real story, build rapport" />
      <ReplyCard angle="CURIOUS"  text="Wait — alone, or who dragged you out there?" why="lightweight probe, opens a thread" />

      <div style={{ background: W.surface2, borderRadius: 12, padding: 14, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ fontSize: 14, color: W.fg, lineHeight: 1.4 }}><span style={{ color: W.fgDim, fontWeight: 700 }}>Read:</span> she's testing your investment by playing busy</div>
        <div style={{ fontSize: 14, color: W.fg, lineHeight: 1.4 }}><span style={{ color: W.fgDim, fontWeight: 700 }}>Move:</span> takeaway, then ping in 48h</div>
      </div>

      {/* Floating add button */}
      <div style={{ position: 'sticky', bottom: 24, display: 'flex', justifyContent: 'center', marginTop: 16, pointerEvents: 'none' }}>
        <Pressable onClick={onAdd} style={{
          pointerEvents: 'auto',
          padding: '12px 18px', borderRadius: 999,
          background: W.accent, color: '#0a0a0f', fontSize: 15, fontWeight: 700,
          display: 'inline-flex', alignItems: 'center', gap: 6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
        }}>
          <Icon name="plus" size={16} strokeWidth={2.25} /> Add new screenshot
        </Pressable>
      </div>
    </div>
  );
}

function ErrorView({ onRetry }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '36px 24px', gap: 20, textAlign: 'center' }}>
      <div style={{ fontSize: 17, fontWeight: 700 }}>Couldn't generate replies — try again?</div>
      <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <PrimaryButton onClick={onRetry}>Retry</PrimaryButton>
        <div style={{ textAlign: 'center' }}>
          <TextLink>Pick another screenshot</TextLink>
        </div>
      </div>
    </div>
  );
}

function ReplyCard({ angle, text, why }) {
  const [copied, setCopied] = React.useState(false);
  const [flash, setFlash] = React.useState(false);
  const angleColor = W.angle[angle];
  const onTap = () => {
    setCopied(true); setFlash(true);
    setTimeout(() => setFlash(false), 800);
  };
  return (
    <Pressable onClick={onTap} as="div" style={{
      background: W.surface, borderRadius: 16, padding: 16,
      border: `1px solid ${flash ? W.accent : W.border}`,
      boxShadow: flash ? `0 0 0 1px ${W.accent} inset` : 'none',
      display: 'flex', flexDirection: 'column', gap: 8, textAlign: 'left',
      transition: 'border-color 800ms cubic-bezier(.2,.8,.2,1), box-shadow 800ms cubic-bezier(.2,.8,.2,1)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: angleColor, lineHeight: 1 }}>{angle}</span>
        <span style={{ fontSize: 13, color: copied ? W.accent : W.fgDimmer, fontWeight: copied ? 600 : 400 }}>
          {copied ? 'Copied ✓' : 'Tap to copy'}
        </span>
      </div>
      <div style={{ fontSize: 17, lineHeight: 1.45, color: W.fg }}>{text}</div>
      {why && <div style={{ fontSize: 13, fontStyle: 'italic', color: W.fgDim }}>{why}</div>}
    </Pressable>
  );
}

function Thumbnail({ active = false, dim = false }) {
  return (
    <div style={{
      width: 220, height: 360, borderRadius: 16,
      background: W.surface, position: 'relative', overflow: 'hidden',
      border: active ? `2px solid ${W.accent}` : `1px solid ${W.border}`,
      opacity: dim ? 0.6 : 1,
    }}>
      {/* fake screenshot content: chat bubbles */}
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ height: 18, width: '60%', background: W.surface2, borderRadius: 9, alignSelf: 'flex-start' }} />
        <div style={{ height: 18, width: '70%', background: W.surface2, borderRadius: 9, alignSelf: 'flex-start' }} />
        <div style={{ height: 18, width: '50%', background: 'rgba(102,224,180,0.18)', borderRadius: 9, alignSelf: 'flex-end' }} />
        <div style={{ height: 18, width: '80%', background: W.surface2, borderRadius: 9, alignSelf: 'flex-start' }} />
        <div style={{ height: 18, width: '40%', background: 'rgba(102,224,180,0.18)', borderRadius: 9, alignSelf: 'flex-end' }} />
        <div style={{ height: 18, width: '65%', background: W.surface2, borderRadius: 9, alignSelf: 'flex-start' }} />
        <div style={{ height: 18, width: '55%', background: 'rgba(102,224,180,0.18)', borderRadius: 9, alignSelf: 'flex-end' }} />
        <div style={{ height: 18, width: '75%', background: W.surface2, borderRadius: 9, alignSelf: 'flex-start' }} />
      </div>
      {dim && <div style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,15,0.4)' }} />}
    </div>
  );
}

function LoadingBanner() {
  return (
    <div style={{
      padding: '10px 16px',
      background: W.accentDim,
      borderTop: `2px solid ${W.accent}`,
      borderBottom: `1px solid ${W.border}`,
      display: 'flex', alignItems: 'center', gap: 10,
      color: W.accent, fontSize: 13, fontWeight: 600,
    }}>
      <Spinner size={14} />
      Reading the chat & generating replies…
    </div>
  );
}

function PhoneIllustration() {
  return (
    <svg width="120" height="120" viewBox="0 0 160 160" fill="none" stroke={W.border} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="38" y="14" width="84" height="132" rx="14" />
      <line x1="68" y1="22" x2="92" y2="22" />
      <rect x="50" y="42" width="50" height="18" rx="9" />
      <rect x="60" y="68" width="50" height="18" rx="9" />
      <rect x="50" y="94" width="40" height="18" rx="9" />
      <path d="M124 36 l6 -6 M130 36 l-6 -6 M127 30 v-8 M127 38 v8" stroke={W.accent} />
    </svg>
  );
}

Object.assign(window, { HomeScreen, ReplyCard, ChatsPill });

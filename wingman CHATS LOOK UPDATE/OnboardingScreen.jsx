// OnboardingScreen — 3-screen carousel with personality.

function OnboardingScreen({ onDone }) {
  const [step, setStep] = React.useState(0);
  const slide = ONB_SLIDES[step];
  const last = step === ONB_SLIDES.length - 1;
  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
      background: W.bg, color: W.fg,
      backgroundImage: slide.bg,
      transition: 'background-image 360ms cubic-bezier(.2,.8,.2,1)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 20px' }}>
        <span style={{ color: W.accent, fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em' }}>Wingman</span>
        <Pressable onClick={onDone} as="span" style={{ color: W.fgDim, fontSize: 14, fontWeight: 600 }}>Skip</Pressable>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 24px', textAlign: 'center', gap: 28, minHeight: 0 }}>
        <OnbIllo step={step} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 340 }}>
          <h1 style={{ fontSize: 30, fontWeight: 700, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15 }}>{slide.h}</h1>
          <p style={{ color: W.fgDim, fontSize: 16, margin: 0, lineHeight: 1.45 }}>{slide.s}</p>
        </div>
      </div>

      <div style={{ padding: '0 24px 32px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8 }}>
          {ONB_SLIDES.map((_, i) => (
            <div key={i} style={{
              width: i === step ? 24 : 6, height: 6, borderRadius: 3,
              background: i === step ? slide.accent : W.fgDimmer,
              transition: 'all 240ms cubic-bezier(.2,.8,.2,1)',
            }} />
          ))}
        </div>
        <PrimaryButton onClick={() => last ? onDone() : setStep(step + 1)}>
          {last ? 'Get started — 10 free replies' : 'Next'}
        </PrimaryButton>
      </div>
    </div>
  );
}

const ONB_SLIDES = [
  {
    h: 'Every chat is a fork in the road.',
    s: 'You\'ve got six conversations open. Three of them deserve a great reply. Wingman handles the hard part.',
    accent: '#66e0b4',
    bg: 'radial-gradient(80% 50% at 50% 8%, rgba(102,224,180,0.16), transparent 65%), radial-gradient(60% 40% at 90% 80%, rgba(255,107,138,0.10), transparent 60%)',
  },
  {
    h: 'Screenshot. We do the rest.',
    s: 'One tap reads the whole thread and writes 5 replies — each from a different angle.',
    accent: '#b36bff',
    bg: 'radial-gradient(70% 45% at 20% 10%, rgba(179,107,255,0.18), transparent 65%), radial-gradient(60% 40% at 85% 90%, rgba(102,224,180,0.10), transparent 60%)',
  },
  {
    h: 'Tap to copy. Paste. Win.',
    s: 'Pick the angle that fits. Wingman remembers what worked. 10 replies on the house.',
    accent: '#ff6b8a',
    bg: 'radial-gradient(70% 45% at 80% 10%, rgba(255,107,138,0.16), transparent 65%), radial-gradient(60% 40% at 15% 90%, rgba(102,224,180,0.14), transparent 60%)',
  },
];

// Render the right illustration for the current step
function OnbIllo({ step }) {
  if (step === 0) return <ChatCollageIllo />;
  if (step === 1) return <CaptureToAnglesIllo />;
  return <CopyMomentIllo />;
}

// ─────────────────────────────────────────────────────────────
// Slide 1 — chat collage. Overlapping cards, each tinted, each rotated.
// ─────────────────────────────────────────────────────────────
function ChatCollageIllo() {
  const cards = [
    {
      name: 'Maya', source: 'iMessage', tint: '#ff6b8a',
      msgs: [
        { from: 'them', text: 'haha okay you got me, that was good' },
        { from: 'them', text: 'so… plans this weekend? 👀' },
      ],
      rot: -7, x: -32, y: 0,  scale: 1.0, z: 1,
    },
    {
      name: 'Amy', source: 'Hinge', tint: '#66e0b4',
      msgs: [
        { from: 'them', text: 'sounds like you\'ve been busy' },
        { from: 'them', text: 'tell me one thing 🙃' },
      ],
      rot: 6, x: 36, y: -18, scale: 1.04, z: 3,
    },
    {
      name: 'Sophie', source: 'Bumble', tint: '#ffc857',
      msgs: [
        { from: 'them', text: 'Tokyo or Lisbon — pick one' },
      ],
      rot: -4, x: 8, y: 70, scale: 0.96, z: 2,
    },
  ];
  return (
    <div style={{ position: 'relative', width: 300, height: 280 }}>
      {cards.map((c, i) => (
        <div key={i} style={{
          position: 'absolute', left: '50%', top: '50%',
          transform: `translate(calc(-50% + ${c.x}px), calc(-50% + ${c.y}px)) rotate(${c.rot}deg) scale(${c.scale})`,
          zIndex: c.z,
        }}>
          <CollageCard {...c} />
        </div>
      ))}
      {/* "?" thought bubble */}
      <div style={{
        position: 'absolute', right: -6, top: 30, zIndex: 5,
        width: 44, height: 44, borderRadius: '50%',
        background: 'linear-gradient(140deg, #2a2a3a, #1a1a25)',
        border: '1px solid #3a3a4a',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: W.fgDim, fontSize: 22, fontWeight: 700,
        boxShadow: '0 8px 22px rgba(0,0,0,0.45)',
      }}>?</div>
    </div>
  );
}

function CollageCard({ name, source, tint, msgs }) {
  return (
    <div style={{
      width: 200, padding: 12, borderRadius: 16,
      background: W.surface, border: `1px solid ${W.border}`,
      display: 'flex', flexDirection: 'column', gap: 8,
      boxShadow: '0 12px 28px rgba(0,0,0,0.5)',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Tinted top stripe */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: tint, opacity: 0.9 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <div style={{
            width: 22, height: 22, borderRadius: '50%',
            background: tint, opacity: 0.9,
            color: '#0a0a0f', fontSize: 10, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>{name[0]}</div>
          <span style={{ fontSize: 13, fontWeight: 700, color: W.fg }}>{name}</span>
        </div>
        <span style={{ fontSize: 10, fontWeight: 600, color: W.fgDimmer, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{source}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {msgs.map((m, i) => (
          <div key={i} style={{
            alignSelf: m.from === 'them' ? 'flex-start' : 'flex-end',
            maxWidth: '88%',
            padding: '7px 10px', borderRadius: 10,
            background: m.from === 'them' ? W.surface2 : 'rgba(102,224,180,0.18)',
            color: m.from === 'them' ? W.fg : '#a8f0d2',
            fontSize: 12, lineHeight: 1.3, textAlign: 'left',
          }}>{m.text}</div>
        ))}
        {/* "you typing" placeholder */}
        <div style={{
          alignSelf: 'flex-end', padding: '7px 10px', borderRadius: 10,
          border: `1.5px dashed ${W.fgDimmer}`,
          color: W.fgDimmer, fontSize: 11,
          display: 'flex', gap: 3, alignItems: 'center',
        }}>
          <span style={{ width: 4, height: 4, borderRadius: 2, background: W.fgDimmer }} />
          <span style={{ width: 4, height: 4, borderRadius: 2, background: W.fgDimmer }} />
          <span style={{ width: 4, height: 4, borderRadius: 2, background: W.fgDimmer }} />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Slide 2 — screenshot snaps into 5 colored angle chips.
// ─────────────────────────────────────────────────────────────
function CaptureToAnglesIllo() {
  const angles = [
    { label: 'BOLD',    color: '#ff8a3d', text: 'Friday, 8pm. My place.' },
    { label: 'PLAYFUL', color: '#b36bff', text: 'Busy is a personality trait now?' },
    { label: 'SEXUAL',  color: '#ff6b8a', text: 'You\'re trouble — dinner?' },
    { label: 'SINCERE', color: '#66e0b4', text: 'What was the moment you\'ll remember?' },
    { label: 'CURIOUS', color: '#5fb8ff', text: 'Wait — alone, or who dragged you?' },
  ];
  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 18 }}>
      {/* Phone screenshot */}
      <div style={{
        width: 110, height: 200, borderRadius: 16,
        background: W.surface, border: `1px solid ${W.border}`,
        position: 'relative', overflow: 'hidden',
        boxShadow: '0 14px 30px rgba(0,0,0,0.5)',
      }}>
        {/* notch */}
        <div style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: 38, height: 14, borderRadius: '0 0 8px 8px', background: '#000' }} />
        <div style={{ padding: '22px 10px 10px', display: 'flex', flexDirection: 'column', gap: 5 }}>
          <div style={{ height: 14, width: '70%', background: W.surface2, borderRadius: 7, alignSelf: 'flex-start' }} />
          <div style={{ height: 14, width: '85%', background: W.surface2, borderRadius: 7, alignSelf: 'flex-start' }} />
          <div style={{ height: 14, width: '55%', background: 'rgba(102,224,180,0.22)', borderRadius: 7, alignSelf: 'flex-end' }} />
          <div style={{ height: 14, width: '78%', background: W.surface2, borderRadius: 7, alignSelf: 'flex-start' }} />
          <div style={{ height: 14, width: '45%', background: 'rgba(102,224,180,0.22)', borderRadius: 7, alignSelf: 'flex-end' }} />
          <div style={{ height: 14, width: '62%', background: W.surface2, borderRadius: 7, alignSelf: 'flex-start' }} />
        </div>
        {/* capture flash gradient */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(135deg, rgba(179,107,255,0.0) 0%, rgba(179,107,255,0.18) 50%, rgba(102,224,180,0.0) 100%)',
          pointerEvents: 'none',
        }} />
        {/* corner brackets */}
        <CornerBrackets color="#b36bff" />
      </div>

      {/* Magic arrow with sparkles */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
        <Sparkle color="#b36bff" />
        <svg width="36" height="14" viewBox="0 0 36 14" fill="none">
          <path d="M2 7 H30 M24 2 L30 7 L24 12" stroke="#b36bff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <Sparkle color="#66e0b4" small />
      </div>

      {/* 5 angle chips, fanning */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {angles.map((a, i) => (
          <div key={i} style={{
            transform: `translateX(${i % 2 === 0 ? 0 : 6}px)`,
            background: W.surface, border: `1px solid ${W.border}`,
            borderRadius: 9, padding: '6px 10px',
            display: 'flex', alignItems: 'center', gap: 8,
            boxShadow: '0 4px 10px rgba(0,0,0,0.35)',
            minWidth: 150,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: 3, background: a.color, flexShrink: 0 }} />
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: a.color, flexShrink: 0 }}>{a.label}</span>
            <span style={{ fontSize: 10, color: W.fgDim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CornerBrackets({ color }) {
  const arm = 14, t = 2.5;
  const corner = (style) => (
    <>
      <div style={{ position: 'absolute', width: arm, height: t, background: color, ...style }} />
      <div style={{ position: 'absolute', width: t, height: arm, background: color, ...style }} />
    </>
  );
  return (
    <>
      <div style={{ position: 'absolute', top: 6, left: 6 }}>
        <div style={{ position: 'absolute', width: arm, height: t, background: color }} />
        <div style={{ position: 'absolute', width: t, height: arm, background: color }} />
      </div>
      <div style={{ position: 'absolute', top: 6, right: 6 }}>
        <div style={{ position: 'absolute', width: arm, height: t, background: color, right: 0 }} />
        <div style={{ position: 'absolute', width: t, height: arm, background: color, right: 0 }} />
      </div>
      <div style={{ position: 'absolute', bottom: 6, left: 6 }}>
        <div style={{ position: 'absolute', width: arm, height: t, background: color, bottom: 0 }} />
        <div style={{ position: 'absolute', width: t, height: arm, background: color, bottom: 0 }} />
      </div>
      <div style={{ position: 'absolute', bottom: 6, right: 6 }}>
        <div style={{ position: 'absolute', width: arm, height: t, background: color, bottom: 0, right: 0 }} />
        <div style={{ position: 'absolute', width: t, height: arm, background: color, bottom: 0, right: 0 }} />
      </div>
    </>
  );
}

function Sparkle({ color, small = false }) {
  const s = small ? 10 : 16;
  return (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="none">
      <path d="M8 0 L9.2 6.8 L16 8 L9.2 9.2 L8 16 L6.8 9.2 L0 8 L6.8 6.8 Z" fill={color} opacity={small ? 0.7 : 0.95} />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// Slide 3 — copy moment. Reply card glowing mint, +1 confidence chip,
// confetti dots. Their message above as the prompt.
// ─────────────────────────────────────────────────────────────
function CopyMomentIllo() {
  return (
    <div style={{ position: 'relative', width: 280 }}>
      {/* Their message */}
      <div style={{
        background: W.surface2, padding: '10px 13px', borderRadius: 14,
        fontSize: 13, color: W.fgDim, alignSelf: 'flex-start',
        maxWidth: '78%', lineHeight: 1.35, marginBottom: 16, textAlign: 'left',
      }}>
        sounds like you've been busy — tell me one thing 🙃
      </div>

      {/* Reply card with mint glow */}
      <div style={{
        background: W.surface, border: `2px solid ${W.accent}`, borderRadius: 16,
        padding: 14, display: 'flex', flexDirection: 'column', gap: 8,
        boxShadow: '0 0 0 6px rgba(102,224,180,0.12), 0 14px 32px rgba(0,0,0,0.5)',
        position: 'relative',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: '#b36bff' }}>PLAYFUL</span>
          <span style={{
            fontSize: 11, color: W.accent, fontWeight: 700,
            display: 'inline-flex', alignItems: 'center', gap: 4,
          }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 6 L5 9 L10 3" stroke="#66e0b4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            Copied
          </span>
        </div>
        <div style={{ fontSize: 14, color: W.fg, textAlign: 'left', lineHeight: 1.4 }}>
          Busy is a personality trait now? Bold of you. Tell me one good thing.
        </div>
      </div>

      {/* +1 confidence chip floating */}
      <div style={{
        position: 'absolute', top: -16, right: -10,
        background: 'linear-gradient(140deg, #ff6b8a, #ffc857)',
        color: '#0a0a0f', fontSize: 11, fontWeight: 700,
        padding: '5px 9px', borderRadius: 999,
        boxShadow: '0 6px 16px rgba(255,107,138,0.35)',
        transform: 'rotate(8deg)',
        display: 'inline-flex', alignItems: 'center', gap: 4,
      }}>
        <span style={{ fontSize: 12 }}>↑</span> +1 confidence
      </div>

      {/* Confetti dots */}
      <Confetti />
    </div>
  );
}

function Confetti() {
  const dots = [
    { x: -18, y: 80,  c: '#66e0b4', s: 6 },
    { x: 295, y: 60,  c: '#b36bff', s: 8 },
    { x: 280, y: 130, c: '#ffc857', s: 5 },
    { x: -10, y: 130, c: '#ff6b8a', s: 6 },
    { x: 30,  y: 195, c: '#5fb8ff', s: 5 },
    { x: 240, y: 200, c: '#66e0b4', s: 7 },
  ];
  return (
    <>
      {dots.map((d, i) => (
        <div key={i} style={{
          position: 'absolute', left: d.x, top: d.y,
          width: d.s, height: d.s, borderRadius: '50%',
          background: d.c, opacity: 0.85,
        }} />
      ))}
    </>
  );
}

window.OnboardingScreen = OnboardingScreen;
window.OnbIllo = OnbIllo;
window.ONB_SLIDES = ONB_SLIDES;

// Wingman shared design tokens + utility components.
// Loaded before screen components.

const W = {
  bg: '#0a0a0f',
  surface: '#13131c',
  surface2: '#1a1a25',
  border: '#2a2a3a',
  fg: '#f5f5f7',
  fgDim: '#9494a3',
  fgDimmer: '#5f5f6e',
  accent: '#66e0b4',
  accentDim: 'rgba(102,224,180,0.12)',
  accentDim2: 'rgba(102,224,180,0.20)',
  accentPress: '#4dcb9c',
  error: '#ff4757',
  angle: {
    BOLD: '#eab308',
    PLAYFUL: '#b36bff',
    SEXUAL: '#ff4757',
    SINCERE: '#5999e8',
    CURIOUS: '#66e0b4',
  },
  font: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Roboto Flex", system-ui, sans-serif',
};

// PressableButton — applies the universal press feedback
function Pressable({ onClick, children, style = {}, disabled = false, as = 'button' }) {
  const [pressed, setPressed] = React.useState(false);
  const Tag = as;
  return (
    <Tag
      onClick={disabled ? undefined : onClick}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      style={{
        transform: pressed ? 'scale(0.96)' : 'scale(1)',
        opacity: disabled ? 0.4 : (pressed ? 0.85 : 1),
        transition: 'transform 200ms cubic-bezier(.2,.8,.2,1), opacity 200ms cubic-bezier(.2,.8,.2,1)',
        cursor: disabled ? 'default' : 'pointer',
        border: 'none', background: 'transparent', padding: 0, font: 'inherit', color: 'inherit',
        ...style,
      }}
    >
      {children}
    </Tag>
  );
}

function PrimaryButton({ children, onClick, disabled, style = {} }) {
  return (
    <Pressable onClick={onClick} disabled={disabled} style={{
      width: '100%', padding: '16px', borderRadius: 16,
      background: W.accent, color: '#0a0a0f', fontSize: 17, fontWeight: 700,
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      ...style,
    }}>{children}</Pressable>
  );
}

function SecondaryButton({ children, onClick, style = {} }) {
  return (
    <Pressable onClick={onClick} style={{
      width: '100%', padding: '14px', borderRadius: 16,
      background: 'transparent', border: `1px solid ${W.accent}`,
      color: W.accent, fontSize: 17, fontWeight: 600,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      ...style,
    }}>{children}</Pressable>
  );
}

function TextLink({ children, onClick, color = W.fgDim, style = {} }) {
  return (
    <Pressable onClick={onClick} as="span" style={{
      color, fontSize: 15, fontWeight: 600, display: 'inline-flex', ...style,
    }}>{children}</Pressable>
  );
}

function Spinner({ size = 20, color = W.accent }) {
  return (
    <div style={{
      width: size, height: size,
      border: `2px solid ${color}40`, borderTopColor: color,
      borderRadius: '50%', animation: 'wm-spin .9s linear infinite',
    }} />
  );
}

// Top bar used on most screens
function TopBar({ leftLabel, leftAction, title, right, hideWordmark, quota }) {
  return (
    <div style={{
      height: 56, padding: '0 16px',
      background: W.surface, borderBottom: `1px solid ${W.border}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      flexShrink: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        {leftLabel && (
          <Pressable onClick={leftAction} style={{ color: W.accent, fontSize: 17, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 22, lineHeight: 1, transform: 'translateY(-1px)' }}>‹</span>{leftLabel}
          </Pressable>
        )}
        {!hideWordmark && !leftLabel && (
          <span style={{ color: W.accent, fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>Wingman</span>
        )}
        {title && (
          <span style={{ color: W.fg, fontSize: 17, fontWeight: 700, marginLeft: leftLabel ? 8 : 0 }}>{title}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {quota && <span style={{ color: W.fgDim, fontSize: 13 }}>{quota}</span>}
        {right}
      </div>
    </div>
  );
}

// Lucide-via-CDN icon helper. Inline-renders the SVG paths inline.
const ICONS = {
  chevronDown: <path d="m6 9 6 6 6-6"/>,
  chevronLeft: <path d="m15 18-6-6 6-6"/>,
  arrowRight: <><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></>,
  plus: <><path d="M12 5v14"/><path d="M5 12h14"/></>,
  refresh: <><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></>,
  more: <><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></>,
  image: <><rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></>,
  check: <path d="M20 6 9 17l-5-5"/>,
  x: <><path d="M18 6 6 18"/><path d="m6 6 12 12"/></>,
  wifiOff: <><path d="M12 20h.01"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/><path d="M5 12.859a10 10 0 0 1 5.17-2.69"/><path d="M19 12.859a10 10 0 0 0-2.007-1.523"/><path d="M2 8.82a15 15 0 0 1 4.177-2.643"/><path d="M22 8.82a15 15 0 0 0-11.288-3.764"/><path d="m2 2 20 20"/></>,
  arrowLeft: <><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></>,
};

function Icon({ name, size = 20, color = 'currentColor', strokeWidth = 1.75 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke={color} strokeWidth={strokeWidth}
         strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block' }}>
      {ICONS[name]}
    </svg>
  );
}

Object.assign(window, { W, Pressable, PrimaryButton, SecondaryButton, TextLink, Spinner, TopBar, Icon });

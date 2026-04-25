// EdgeStates.jsx — additional screens to complete the brief:
// no-internet, server-down, permission-denied, generation-timeout,
// unclear-screenshot, push-notification, paywall-during-generation,
// settings.

// ─────────────────────────────────────────────────────────────
// Banners (top-of-screen, sticky)
// ─────────────────────────────────────────────────────────────
function NoInternetBanner() {
  return (
    <div style={{
      padding: '10px 16px',
      background: 'rgba(255,71,87,0.10)',
      borderTop: `2px solid ${W.error}`,
      borderBottom: `1px solid ${W.border}`,
      display: 'flex', alignItems: 'center', gap: 10,
      color: W.error, fontSize: 13, fontWeight: 600,
    }}>
      <Icon name="wifiOff" size={14} color={W.error} strokeWidth={2} />
      <span style={{ flex: 1 }}>No connection — replies need internet</span>
      <Pressable as="span" style={{ color: W.error, fontSize: 13, fontWeight: 700 }}>Retry</Pressable>
    </div>
  );
}

function ServerDownBanner() {
  return (
    <div style={{
      padding: '10px 16px',
      background: W.surface2,
      borderBottom: `1px solid ${W.border}`,
      display: 'flex', alignItems: 'center', gap: 10,
      color: W.fgDim, fontSize: 13, fontWeight: 600,
    }}>
      <span style={{ width: 8, height: 8, borderRadius: 4, background: W.error, flexShrink: 0 }} />
      <span style={{ flex: 1 }}>Wingman is down for maintenance.</span>
      <Pressable as="span" style={{ color: W.accent, fontSize: 13, fontWeight: 700 }}>Refresh</Pressable>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home variant: no internet
// ─────────────────────────────────────────────────────────────
function HomeNoInternet() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota="Free · 7 left"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      <NoInternetBanner />
      <div style={{ flex: 1, padding: '32px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 20 }}>
        <div style={{
          width: 72, height: 72, borderRadius: '50%',
          background: 'rgba(255,71,87,0.10)',
          border: `1px solid rgba(255,71,87,0.25)`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: W.error,
        }}>
          <Icon name="wifiOff" size={28} strokeWidth={1.75} color={W.error} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 280 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>You're offline</h1>
          <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>Replies need internet to generate. Reconnect to keep going.</p>
        </div>
        <div style={{ width: '100%', marginTop: 4 }}>
          <PrimaryButton>Try again</PrimaryButton>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home variant: server down
// ─────────────────────────────────────────────────────────────
function HomeServerDown() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota="Pro · 12/200"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      <ServerDownBanner />
      <div style={{ flex: 1, padding: '40px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 20 }}>
        <div style={{
          width: 72, height: 72, borderRadius: 16,
          background: W.surface,
          border: `1px solid ${W.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: W.fgDim,
          fontSize: 28, fontWeight: 700, fontFamily: 'ui-monospace, SFMono-Regular, monospace',
        }}>502</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 300 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Down for maintenance</h1>
          <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>Wingman is back in a few minutes. Your chats are safe.</p>
        </div>
        <div style={{ width: '100%', marginTop: 4 }}>
          <PrimaryButton>Refresh</PrimaryButton>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home variant: photo permission denied
// ─────────────────────────────────────────────────────────────
function HomePermissionDenied() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota="Free · 10 trial left"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      <div style={{ flex: 1, padding: '40px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 24 }}>
        <svg width="120" height="120" viewBox="0 0 160 160" fill="none" stroke={W.border} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="28" y="34" width="104" height="76" rx="8" />
          <circle cx="62" cy="68" r="6" />
          <path d="M28 96 l28 -28 l24 24 l16 -16 l36 30" />
          <circle cx="120" cy="44" r="14" stroke={W.error} strokeWidth="2" />
          <path d="M111 35 l18 18" stroke={W.error} strokeWidth="2" />
        </svg>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 300 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Wingman needs photo access</h1>
          <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>To read screenshots, we need permission to your photo library. Nothing leaves your phone unencrypted.</p>
        </div>
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12, marginTop: 4 }}>
          <PrimaryButton>Open settings</PrimaryButton>
          <div style={{ textAlign: 'center' }}>
            <TextLink>Pick a screenshot manually</TextLink>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home variant: generation timeout (>30s)
// ─────────────────────────────────────────────────────────────
function HomeTimeout() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota="Pro · 12/200"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      <div style={{
        padding: '10px 16px',
        background: 'rgba(234,179,8,0.10)',
        borderTop: `2px solid #eab308`,
        borderBottom: `1px solid ${W.border}`,
        display: 'flex', alignItems: 'center', gap: 10,
        color: '#eab308', fontSize: 13, fontWeight: 600,
      }}>
        <Spinner size={14} color="#eab308" />
        Taking longer than usual…
      </div>
      <div style={{ flex: 1, padding: '32px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
        <div style={{ position: 'relative' }}>
          <div style={{
            width: 220, height: 360, borderRadius: 16,
            background: W.surface, border: `1px solid ${W.border}`,
            opacity: 0.5, position: 'relative', overflow: 'hidden',
          }}>
            <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[60, 70, 50, 80, 40, 65, 55, 75].map((w, i) => (
                <div key={i} style={{
                  height: 18, width: `${w}%`,
                  background: i % 3 === 2 ? 'rgba(102,224,180,0.18)' : W.surface2,
                  borderRadius: 9,
                  alignSelf: i % 3 === 2 ? 'flex-end' : 'flex-start',
                }} />
              ))}
            </div>
          </div>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spinner size={36} color="#eab308" />
          </div>
        </div>
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 280 }}>
          <div style={{ color: W.fg, fontSize: 17, fontWeight: 700 }}>This one's a tough chat</div>
          <div style={{ color: W.fgDim, fontSize: 13, lineHeight: 1.4 }}>Hang tight — almost there. Or cancel and try a clearer screenshot.</div>
        </div>
        <div style={{ width: '100%', marginTop: 4 }}>
          <SecondaryButton>Cancel</SecondaryButton>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home variant: unclear screenshot
// ─────────────────────────────────────────────────────────────
function HomeUnclear() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar
        quota="Pro · 12/200"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      <div style={{ flex: 1, padding: '32px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 20 }}>
        <div style={{ position: 'relative' }}>
          <div style={{
            width: 180, height: 280, borderRadius: 14,
            background: W.surface, border: `1px solid ${W.border}`,
            position: 'relative', overflow: 'hidden',
            filter: 'blur(2px)',
          }}>
            <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 5 }}>
              {[60, 70, 50, 80, 40].map((w, i) => (
                <div key={i} style={{
                  height: 14, width: `${w}%`,
                  background: i % 3 === 2 ? 'rgba(102,224,180,0.18)' : W.surface2,
                  borderRadius: 7,
                  alignSelf: i % 3 === 2 ? 'flex-end' : 'flex-start',
                }} />
              ))}
            </div>
          </div>
          <div style={{
            position: 'absolute', top: -6, right: -6,
            width: 32, height: 32, borderRadius: '50%',
            background: W.bg, border: `2px solid ${W.error}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: W.error, fontSize: 18, fontWeight: 700,
          }}>!</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 300 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Couldn't read this clearly</h1>
          <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>Try a sharper screenshot — full chat visible, no zoom, no crop.</p>
        </div>
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12, marginTop: 4 }}>
          <PrimaryButton>Pick another screenshot</PrimaryButton>
          <div style={{ textAlign: 'center' }}>
            <TextLink>Try this one again</TextLink>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Home: paywall-during-generation overlay
// (paywall sheet rises mid-generation — typed extra context preserved)
// ─────────────────────────────────────────────────────────────
function HomePaywallMidGen() {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg, position: 'relative' }}>
      <TopBar
        quota="Free · 0 left"
        right={
          <>
            <Pressable as="span" style={{ color: W.accent, fontSize: 15, fontWeight: 600 }}>Chats</Pressable>
            <Pressable style={{ width: 32, height: 32, borderRadius: '50%', background: W.surface2, border: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: W.fgDim }}>
              <Icon name="more" size={16} />
            </Pressable>
          </>
        }
      />
      {/* Generating beneath */}
      <div style={{ padding: '10px 16px', background: W.accentDim, borderTop: `2px solid ${W.accent}`, borderBottom: `1px solid ${W.border}`, display: 'flex', alignItems: 'center', gap: 10, color: W.accent, fontSize: 13, fontWeight: 600 }}>
        <Spinner size={14} />
        Reading the chat & generating replies…
      </div>
      <div style={{ flex: 1, padding: '32px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20, opacity: 0.4 }}>
        <div style={{
          width: 220, height: 360, borderRadius: 16,
          background: W.surface, border: `1px solid ${W.border}`,
          opacity: 0.6,
        }} />
        <div style={{ color: W.fg, fontSize: 17, fontWeight: 700 }}>Crafting your replies</div>
      </div>

      {/* Scrim + sheet */}
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 5 }} />
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        background: W.bg, borderTopLeftRadius: 24, borderTopRightRadius: 24,
        borderTop: `1px solid ${W.border}`,
        padding: '12px 20px 24px',
        zIndex: 6,
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 4, paddingBottom: 4 }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: W.fgDimmer }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: W.accent }}>YOUR CHAT IS SAVED</div>
          <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Out of free replies</h2>
          <p style={{ color: W.fgDim, fontSize: 15, margin: 0, lineHeight: 1.4 }}>Upgrade to finish this generation. Your screenshot is already in the queue.</p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            { t: 'Weekly', p: '$4.99', sub: 'Quick boost', sel: false },
            { t: 'Monthly', p: '$14.99', sub: 'Most popular', sel: true, tag: 'POPULAR' },
            { t: 'Yearly', p: '$89', sub: 'Save 50%', sel: false, tag: '−50%' },
          ].map(plan => (
            <div key={plan.t} style={{
              position: 'relative',
              background: W.surface,
              border: `${plan.sel ? 2 : 1}px solid ${plan.sel ? W.accent : W.border}`,
              borderRadius: 14, padding: '12px 14px',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              {plan.tag && (
                <span style={{
                  position: 'absolute', top: -8, right: 12,
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
                  padding: '3px 7px', borderRadius: 999,
                  background: plan.sel ? W.accent : W.surface2,
                  color: plan.sel ? '#0a0a0f' : W.accent,
                  border: plan.sel ? 'none' : `1px solid ${W.accent}`,
                }}>{plan.tag}</span>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: 15, fontWeight: 700 }}>{plan.t}</span>
                <span style={{ fontSize: 12, color: W.fgDim }}>{plan.sub}</span>
              </div>
              <span style={{ fontSize: 17, fontWeight: 700, color: plan.sel ? W.accent : W.fg }}>{plan.p}</span>
            </div>
          ))}
        </div>

        <PrimaryButton>Start free trial & finish</PrimaryButton>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Push notification — lock-screen mockup
// ─────────────────────────────────────────────────────────────
function PushNotification() {
  return (
    <div style={{
      flex: 1, minHeight: 0, position: 'relative',
      background: 'linear-gradient(180deg, #0a0a0f 0%, #1a1a25 60%, #2a2a3a 100%)',
      color: W.fg, padding: '60px 16px 0',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 28,
    }}>
      {/* Lock-screen time */}
      <div style={{ textAlign: 'center', marginTop: 24 }}>
        <div style={{ fontSize: 14, color: W.fg, opacity: 0.85, fontWeight: 500 }}>Friday, 8 November</div>
        <div style={{ fontSize: 84, fontWeight: 200, letterSpacing: '-0.02em', lineHeight: 1, marginTop: 4 }}>9:41</div>
      </div>

      {/* Notification card */}
      <div style={{
        width: '100%', maxWidth: 360,
        background: 'rgba(40,40,55,0.55)',
        backdropFilter: 'blur(40px) saturate(180%)',
        WebkitBackdropFilter: 'blur(40px) saturate(180%)',
        borderRadius: 18, padding: 14,
        border: '0.5px solid rgba(255,255,255,0.12)',
        display: 'flex', gap: 10, alignItems: 'flex-start',
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8,
          background: W.bg, border: `1px solid ${W.accent}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: W.accent, fontSize: 18, fontWeight: 700,
          fontFamily: W.font, flexShrink: 0,
        }}>›</div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: W.fg, opacity: 0.9 }}>WINGMAN</span>
            <span style={{ fontSize: 12, color: W.fg, opacity: 0.55 }}>now</span>
          </div>
          <div style={{ fontSize: 15, fontWeight: 600, color: W.fg }}>Your reply is ready ✓</div>
          <div style={{ fontSize: 14, color: W.fg, opacity: 0.75, lineHeight: 1.35 }}>5 replies for Amy · tap to copy</div>
        </div>
      </div>

      {/* Faded second notification */}
      <div style={{
        width: '92%', maxWidth: 340, marginTop: -16,
        background: 'rgba(40,40,55,0.35)',
        backdropFilter: 'blur(40px) saturate(180%)',
        WebkitBackdropFilter: 'blur(40px) saturate(180%)',
        borderRadius: 16, padding: 12,
        border: '0.5px solid rgba(255,255,255,0.08)',
        opacity: 0.7,
      }}>
        <div style={{ fontSize: 12, color: W.fg, opacity: 0.6, fontWeight: 600 }}>MESSAGES · earlier</div>
        <div style={{ fontSize: 13, color: W.fg, opacity: 0.7 }}>Amy: hey, sorry — crazy week</div>
      </div>

      {/* Lock indicators */}
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: W.fg, opacity: 0.55, fontSize: 13, marginBottom: 32 }}>
        <span style={{ fontSize: 14 }}>🔒</span>
        <span style={{ fontWeight: 500 }}>Slide up to unlock</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Settings screen
// ─────────────────────────────────────────────────────────────
function SettingsScreen({ onBack }) {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: W.bg, color: W.fg }}>
      <TopBar leftLabel="Back" leftAction={onBack} title="Settings" />
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 16px 32px', display: 'flex', flexDirection: 'column', gap: 24 }}>

        <SettingsSection label="ACCOUNT">
          <SettingsRow label="Email" detail="alex@hey.com" />
          <SettingsRow label="Display name" detail="Alex" chevron />
          <SettingsRow label="Plan" detail={<span style={{ color: W.accent, fontWeight: 700 }}>Pro</span>} chevron />
          <SettingsRow label="Manage subscription" chevron />
          <SettingsRow label="Delete account" danger />
        </SettingsSection>

        <SettingsSection label="PREFERENCES">
          <SettingsRow label="Theme" detail="Dark" chevron />
          <ToneRow />
          <SettingsRow label="Save chats automatically" toggle on />
          <SettingsRow label="Haptic feedback" toggle on />
        </SettingsSection>

        <SettingsSection label="ABOUT">
          <SettingsRow label="Privacy Policy" chevron />
          <SettingsRow label="Terms of Service" chevron />
          <SettingsRow label="Contact support" chevron />
          <SettingsRow label="Version" detail="1.0.4 (build 218)" />
        </SettingsSection>

        <Pressable as="div" style={{ textAlign: 'center', padding: 8, color: W.fgDimmer, fontSize: 13 }}>
          Sign out
        </Pressable>
      </div>
    </div>
  );
}

function SettingsSection({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ padding: '0 6px', fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: W.fgDim }}>{label}</div>
      <div style={{ background: W.surface, border: `1px solid ${W.border}`, borderRadius: 16, overflow: 'hidden' }}>
        {(() => {
          const items = React.Children.toArray(children);
          return items.map((c, i) => React.cloneElement(c, { isLast: i === items.length - 1 }));
        })()}
      </div>
    </div>
  );
}

function SettingsRow({ label, detail, chevron, danger, toggle, on, isLast }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 16px',
      borderBottom: isLast ? 'none' : `1px solid ${W.border}`,
      cursor: 'pointer',
    }}>
      <span style={{ fontSize: 15, fontWeight: 500, color: danger ? W.error : W.fg }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {detail && <span style={{ fontSize: 14, color: W.fgDim }}>{detail}</span>}
        {toggle && (
          <div style={{
            width: 42, height: 26, borderRadius: 13,
            background: on ? W.accent : W.surface2,
            border: on ? 'none' : `1px solid ${W.border}`,
            position: 'relative',
            transition: 'background 200ms cubic-bezier(.2,.8,.2,1)',
          }}>
            <div style={{
              position: 'absolute',
              left: on ? 18 : 2, top: 2,
              width: 22, height: 22, borderRadius: '50%',
              background: '#fff',
              transition: 'left 200ms cubic-bezier(.2,.8,.2,1)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
            }} />
          </div>
        )}
        {chevron && (
          <svg width="8" height="14" viewBox="0 0 8 14" style={{ flexShrink: 0 }}>
            <path d="M1 1l6 6-6 6" stroke={W.fgDimmer} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
      </div>
    </div>
  );
}

function ToneRow() {
  const [val, setVal] = React.useState(6);
  return (
    <div style={{ padding: '14px 16px', borderBottom: `1px solid ${W.border}`, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 15, fontWeight: 500 }}>Default tone</span>
        <span style={{ fontSize: 13, color: W.accent, fontWeight: 600 }}>{val < 4 ? 'Bold' : val < 7 ? 'Balanced' : 'Receptive'}</span>
      </div>
      <div style={{ position: 'relative', height: 4, background: W.surface2, borderRadius: 2 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${val * 10}%`, background: W.accent, borderRadius: 2 }} />
        <div style={{
          position: 'absolute', top: '50%', left: `calc(${val * 10}% - 9px)`,
          transform: 'translateY(-50%)',
          width: 18, height: 18, borderRadius: '50%',
          background: W.fg, border: `2px solid ${W.accent}`,
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: W.fgDimmer, fontWeight: 600, letterSpacing: '0.04em' }}>
        <span>BOLD</span>
        <span>RECEPTIVE</span>
      </div>
    </div>
  );
}

Object.assign(window, {
  HomeNoInternet, HomeServerDown, HomePermissionDenied,
  HomeTimeout, HomeUnclear, HomePaywallMidGen,
  PushNotification, SettingsScreen,
});

// Auth screen — sign-up / log-in toggle. Single column, generous vertical padding.

function AuthScreen({ onSubmit }) {
  const [mode, setMode] = React.useState('signup'); // 'signup' | 'login'
  const [email, setEmail] = React.useState('');
  const [pw, setPw] = React.useState('');
  const [name, setName] = React.useState('');
  const isSignup = mode === 'signup';

  return (
    <div style={{
      flex: 1, minHeight: 0, overflowY: 'auto',
      background: W.bg, color: W.fg,
      // subtle radial mint glow, top-center
      backgroundImage: 'radial-gradient(80% 50% at 50% -10%, rgba(102,224,180,0.08), transparent 70%)',
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ padding: '64px 24px 32px', display: 'flex', flexDirection: 'column', gap: 32 }}>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ color: W.accent, fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em' }}>Wingman</div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1.2, margin: 0 }}>
            Better replies, every time.
          </h1>
          <p style={{ color: W.fgDim, fontSize: 15, lineHeight: 1.4, margin: 0 }}>
            {isSignup ? 'Generate 10 replies free. No credit card.' : 'Welcome back.'}
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field placeholder="you@email.com" value={email} onChange={setEmail} type="email" />
          <Field placeholder="Password (8+ chars)" value={pw} onChange={setPw} type="password" />
          {isSignup && <Field placeholder="Display name (optional)" value={name} onChange={setName} />}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <PrimaryButton onClick={onSubmit}>
            {isSignup ? 'Create account' : 'Log in'}
          </PrimaryButton>
          <div style={{ textAlign: 'center', fontSize: 15 }}>
            <span style={{ color: W.fgDim }}>{isSignup ? 'Have an account? ' : 'New here? '}</span>
            <TextLink onClick={() => setMode(isSignup ? 'login' : 'signup')} color={W.accent}>
              {isSignup ? 'Log in' : 'Sign up'}
            </TextLink>
          </div>
          {!isSignup && (
            <div style={{ textAlign: 'center' }}>
              <TextLink>Forgot password</TextLink>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 'auto', padding: '16px 24px 32px', textAlign: 'center' }}>
        <p style={{ color: W.fgDimmer, fontSize: 12, lineHeight: 1.5, margin: 0 }}>
          By continuing you agree to the <span style={{ color: W.fgDim, fontWeight: 600 }}>Terms of Service</span> and <span style={{ color: W.fgDim, fontWeight: 600 }}>Privacy Policy</span>.
        </p>
      </div>
    </div>
  );
}

function Field({ placeholder, value, onChange, type = 'text' }) {
  const [focused, setFocused] = React.useState(false);
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        width: '100%', padding: '14px 16px',
        background: W.surface,
        border: `1px solid ${focused ? W.accent : W.border}`,
        boxShadow: focused ? `0 0 0 4px ${W.accentDim}` : 'none',
        borderRadius: 10,
        color: W.fg, fontSize: 15, fontFamily: W.font,
        outline: 'none',
        transition: 'all 200ms cubic-bezier(.2,.8,.2,1)',
        boxSizing: 'border-box',
      }}
    />
  );
}

window.AuthScreen = AuthScreen;

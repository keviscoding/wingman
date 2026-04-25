// PaywallSheet — modal sheet, slides up from bottom.

function PaywallSheet({ open, onDismiss }) {
  const [selected, setSelected] = React.useState('monthly');

  return (
    <>
      {/* scrim */}
      <div onClick={onDismiss} style={{
        position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)',
        opacity: open ? 1 : 0, pointerEvents: open ? 'auto' : 'none',
        transition: 'opacity 280ms cubic-bezier(.2,.8,.2,1)',
        zIndex: 5,
      }} />
      {/* sheet */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        background: W.bg, borderTopLeftRadius: 24, borderTopRightRadius: 24,
        borderTop: `1px solid ${W.border}`,
        padding: '12px 20px 32px',
        transform: open ? 'translateY(0)' : 'translateY(100%)',
        transition: 'transform 280ms cubic-bezier(.2,.8,.2,1)',
        zIndex: 6,
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        {/* drag handle */}
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 4, paddingBottom: 8 }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: W.fgDimmer }} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>Out of free replies</h2>
            <p style={{ color: W.fgDim, fontSize: 15, margin: 0, lineHeight: 1.4 }}>Upgrade to keep generating. Cancel anytime.</p>
          </div>
          <Pressable onClick={onDismiss} style={{ color: W.fgDim, padding: 4 }}>
            <Icon name="chevronDown" size={20} />
          </Pressable>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PlanCard id="weekly"  title="Weekly"  price="$4.99 / wk"   sub="Best for a quick boost"  selected={selected === 'weekly'}  onSelect={setSelected} />
          <PlanCard id="monthly" title="Monthly" price="$14.99 / mo" sub="Most popular"             selected={selected === 'monthly'} onSelect={setSelected} tag="MOST POPULAR" />
          <PlanCard id="yearly"  title="Yearly"  price="$89 / yr"     sub="Save 50% vs monthly"     selected={selected === 'yearly'}  onSelect={setSelected} tag="SAVE 50%" />
        </div>

        <p style={{ color: W.fgDimmer, fontSize: 12, textAlign: 'center', margin: 0, lineHeight: 1.5 }}>Includes 7-day free trial · cancel anytime in App Store</p>
        <PrimaryButton onClick={onDismiss}>Start free trial</PrimaryButton>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 16, paddingTop: 4 }}>
          <TextLink>Restore</TextLink>
          <TextLink>Privacy</TextLink>
          <TextLink>Terms</TextLink>
        </div>
      </div>
    </>
  );
}

function PlanCard({ id, title, price, sub, selected, onSelect, tag }) {
  const isPopular = tag === 'MOST POPULAR';
  return (
    <Pressable onClick={() => onSelect(id)} as="div" style={{
      position: 'relative',
      background: W.surface,
      border: `${selected ? 2 : 1}px solid ${selected ? W.accent : W.border}`,
      borderRadius: 16, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 4, textAlign: 'left',
    }}>
      {tag && (
        <span style={{
          position: 'absolute', top: -10, right: 14,
          fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
          padding: '4px 8px', borderRadius: 999,
          background: isPopular ? W.accent : W.surface2,
          color: isPopular ? '#0a0a0f' : W.accent,
          border: isPopular ? 'none' : `1px solid ${W.accent}`,
        }}>{tag}</span>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 17, fontWeight: 700 }}>{title}</span>
        <span style={{ fontSize: 17, fontWeight: 700, color: selected ? W.accent : W.fg }}>{price}</span>
      </div>
      <span style={{ fontSize: 13, color: W.fgDim }}>{sub}</span>
    </Pressable>
  );
}

window.PaywallSheet = PaywallSheet;

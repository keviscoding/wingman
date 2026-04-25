// Deterministic per-name HSL tint so each contact gets a visually
// stable color across the chats list, recent rail, chat detail header,
// etc. Same name → same color forever.
//
// (RN doesn't support oklch like the web mockup; HSL with low
// saturation / mid lightness gives the same calm "warm tinted" feel.)

export type Tint = { bg: string; fg: string };

export function nameTint(name: string): Tint {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  return {
    bg: `hsl(${hue}, 22%, 30%)`,
    fg: `hsl(${hue}, 30%, 86%)`,
  };
}

export function initials(name: string): string {
  // Strip parenthetical source like "(Hinge)" before deriving initials
  const clean = name.replace(/\(.*?\)/g, "").trim();
  const parts = clean.split(/\s+/).slice(0, 2);
  return parts
    .map((p) => p[0] || "")
    .join("")
    .toUpperCase();
}

// Wingman design tokens — mirrors WINGMAN UI/colors_and_type.css 1:1.
// Anything visual in the app should reach for one of these values.
export const theme = {
  // Surfaces
  bg: "#0a0a0f",
  bgElev: "#13131c",
  surface: "#13131c",
  surface2: "#1a1a25",
  border: "#2a2a3a",

  // Text
  text: "#f5f5f7",
  fg: "#f5f5f7",
  dim: "#9494a3",
  fgDim: "#9494a3",
  dimmer: "#5f5f6e",
  fgDimmer: "#5f5f6e",

  // Accent — the only color that pops
  accent: "#66e0b4",
  accentDim: "rgba(102,224,180,0.12)",
  accentPress: "#4dcb9c",

  // Semantic
  red: "#ff4757",
  error: "#ff4757",
  blue: "#5999e8",
  gold: "#eab308",
  purple: "#b36bff",

  // Reply angle label colors
  angle: {
    BOLD: "#eab308",
    PLAYFUL: "#b36bff",
    SEXUAL: "#ff4757",
    SINCERE: "#5999e8",
    CURIOUS: "#66e0b4",
  } as const,

  // Radii
  radii: {
    sm: 6,
    md: 10,
    lg: 16,
    xl: 24,
    pill: 999,
  },

  // Spacing — 8pt grid
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
    xxl: 32,
  },

  // Type scale
  fontSizes: {
    sm: 13,
    md: 15,
    lg: 17,
    xl: 22,
    xxl: 28,
  },
  fontWeights: {
    regular: "400" as const,
    medium: "500" as const,
    semibold: "600" as const,
    bold: "700" as const,
  },
  lineHeights: {
    tight: 1.2,
    body: 1.4,
    reply: 1.45,
  },
  tracking: {
    tight: -0.2, // ~-0.01em on 17px
    display: -0.5, // ~-0.02em on 28px
    label: 1.0, // ~0.08em on 11px (uppercase labels)
  },

  // Motion (use as durationMs in Animated)
  motion: {
    fast: 200,
    base: 240,
    slow: 280,
  },

  // Press feedback
  press: {
    scale: 0.96,
    opacity: 0.85,
  },

  // Layout
  layout: {
    topBarH: 56,
    tapTarget: 44,
  },
};

export type Theme = typeof theme;
export type Angle = keyof typeof theme.angle;

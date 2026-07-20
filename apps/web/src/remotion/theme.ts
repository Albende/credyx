export const theme = {
  bg: { base: 'hsl(232 22% 6%)', elevated: 'hsl(232 18% 9%)' },
  fg: { default: 'hsl(220 14% 96%)', muted: 'hsl(225 10% 68%)' },
  brand: { primary: 'hsl(252 95% 64%)', secondary: 'hsl(35 92% 62%)' },
  accent: 'hsl(174 72% 56%)',
  success: 'hsl(150 60% 48%)',
} as const;

export type Theme = typeof theme;

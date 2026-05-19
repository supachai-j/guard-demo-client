// Short labels for the active guardrail provider, used in compact UI surfaces
// (chat blocking badge, overlay header, blocked-message body).
//
// Single source so ChatWidget and LakeraOverlay stay in sync. Full vendor
// names live in the backend registry (display_name) and on the Admin →
// Providers tab; keep these short enough that "<label> Blocking" fits a
// one-line button at any width.

export const GUARDRAIL_SHORT_LABELS: Record<string, string> = {
  lakera: 'Lakera',
  openai_moderation: 'OpenAI',
  bedrock: 'Bedrock',
  azure_content_safety: 'Azure',
  palo_alto_airs: 'Prisma AIRS',
  cloudflare_firewall_ai: 'Cloudflare',
};

export const guardrailShortLabel = (providerId?: string | null): string =>
  (providerId && GUARDRAIL_SHORT_LABELS[providerId]) || 'Guardrail';

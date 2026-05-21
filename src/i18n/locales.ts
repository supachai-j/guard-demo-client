// EN/TH translations for the public demo surfaces (Landing, Chat, dialogs).
// Admin Console intentionally stays English — operator-facing.

export type Lang = 'en' | 'th';

type _EnLiteral = typeof EN;
export type Dict = Record<keyof _EnLiteral, string>;

export const EN = {
  // Header / nav
  guardActive: 'Guard Active',
  guardInactive: 'Guard Inactive',
  aboutUs: 'About Us',
  toggleTheme: 'Toggle theme',
  toggleLanguage: 'Toggle language',

  // Hero CTAs
  getStarted: 'Get Started',
  learnMore: 'Learn More',
  compareCta: 'Compare with/without Guard',
  compareCtaTooltip: 'Run the same prompt with and without {provider}, side by side',

  // Hero features
  feat1Title: 'AI-Powered Security',
  feat1Body: 'Advanced content moderation and guardrails — pluggable across Lakera, OpenAI, Bedrock, Azure, Prisma AIRS, and Cloudflare.',
  feat2Title: 'Secure RAG System',
  feat2Body: 'AI-powered content with guardrail-protected intelligent responses.',
  feat3Title: 'Tool Integration',
  feat3Body: 'Confidently integrate with external MCP tools and APIs via ToolHive.',

  // Scenario switcher
  demoCompany: 'Demo company',
  scenariosLoadError: 'Could not load demo scenarios',

  // Chat widget
  chatTitle: 'AI Assistant',
  chatPlaceholder: 'Type a message…',
  send: 'Send',
  thinking: 'Thinking…',

  // Compare dialog
  compareTitle: 'Compare with vs. without guardrail',
  compareSubtitle: 'Same prompt, same model — only the guardrail differs.',
  comparePromptPlaceholder: 'Type a prompt to test — try a malicious one to see the guardrail block it.',
  compareQuickTest: 'Quick test:',
  compareRunning: 'Running both…',
  compareRun: 'Run comparison',
  withGuard: 'With',
  withoutGuard: 'Without guardrail',
  blocked: 'BLOCKED',
  allowed: 'ALLOWED',
  unfiltered: 'UNFILTERED',
  responsePlaceholder: 'Response will appear here.',
  runningWithGuard: 'Running with guardrail…',
  runningWithoutGuard: 'Running without guardrail…',
  detectorsFired: 'Detectors that fired:',
  compareFooterTip: 'Tip: a benign prompt should look the same on both sides — the panes only diverge when the guardrail detects a threat.',
  malicious: 'malicious',
  close: 'Close',

  // Guardrail overlay (provider name injected at render via {provider} token)
  guardrailResults: '{provider} Results',
  noLakeraResult: 'No guardrail result available yet — send a chat message first.',
  flagged: 'Flagged',
  clean: 'Clean',
  loadingResults: 'Loading guardrail results…',
  guardrailsTriggered: 'Guardrails triggered',
  allClear: 'All clear',
  noResult: 'No result available',
  violationSummary: 'Violation Summary',
  guardrailDetails: 'Guardrail Details',
  rawJson: 'Raw JSON',
  contentFlagged: 'Content Flagged',
  contentFlaggedBody: 'This content has been flagged by {provider}.',
  requestId: 'Request ID',
  refresh: 'Refresh',
  detected: 'Detected',
  clearStatus: 'Clear',

  // Admin shell (minimal — operator tool, EN-first)
  adminConsole: 'Admin Console',
  backToDemo: 'Back to Demo',
  tabSetup: 'Setup',
  tabBranding: 'Branding',
  tabLLM: 'LLM',
  tabRag: 'RAG',
  tabRagScanning: 'RAG Scanning Report',
  tabTools: 'Connectors',
  tabSecurity: 'Security',
  tabPrompts: 'Demo Prompts',
  tabExport: 'Export/Import',
} as const;

export const TH: Dict = {
  // Header / nav
  guardActive: 'Guard เปิดอยู่',
  guardInactive: 'Guard ปิดอยู่',
  aboutUs: 'เกี่ยวกับเรา',
  toggleTheme: 'สลับธีม',
  toggleLanguage: 'สลับภาษา',

  // Hero CTAs
  getStarted: 'เริ่มใช้งาน',
  learnMore: 'เรียนรู้เพิ่มเติม',
  compareCta: 'เปรียบเทียบเปิด/ปิด Guard',
  compareCtaTooltip: 'รัน prompt เดียวกันคู่กัน เปิด {provider} กับ ปิด',

  // Hero features
  feat1Title: 'ความปลอดภัยด้วย AI',
  feat1Body: 'ตรวจสอบเนื้อหาและตั้ง guardrails — ใช้ได้ทั้ง Lakera, OpenAI, Bedrock, Azure, Prisma AIRS, และ Cloudflare',
  feat2Title: 'ระบบ RAG ที่ปลอดภัย',
  feat2Body: 'สร้างเนื้อหาด้วย AI ตอบคำถามอย่างชาญฉลาด คุ้มครองด้วย guardrails',
  feat3Title: 'เชื่อมต่อเครื่องมือ',
  feat3Body: 'เชื่อมต่อ MCP tools และ APIs ภายนอกผ่าน ToolHive ได้อย่างมั่นใจ',

  // Scenario switcher
  demoCompany: 'บริษัทตัวอย่าง',
  scenariosLoadError: 'ไม่สามารถโหลด scenarios ได้',

  // Chat widget
  chatTitle: 'ผู้ช่วย AI',
  chatPlaceholder: 'พิมพ์ข้อความ…',
  send: 'ส่ง',
  thinking: 'กำลังคิด…',

  // Compare dialog
  compareTitle: 'เปรียบเทียบเปิด vs ปิด guardrail',
  compareSubtitle: 'Prompt เดียวกัน โมเดลเดียวกัน — ต่างกันแค่ guardrail',
  comparePromptPlaceholder: 'พิมพ์ prompt เพื่อทดสอบ — ลอง prompt อันตรายดูว่า guardrail บล็อกไหม',
  compareQuickTest: 'ลองทันที:',
  compareRunning: 'กำลังรันทั้งสองด้าน…',
  compareRun: 'เริ่มเปรียบเทียบ',
  withGuard: 'มี',
  withoutGuard: 'ไม่มี guardrail',
  blocked: 'บล็อก',
  allowed: 'อนุญาต',
  unfiltered: 'ไม่ผ่านการกรอง',
  responsePlaceholder: 'คำตอบจะแสดงตรงนี้',
  runningWithGuard: 'กำลังรันโดยมี guardrail…',
  runningWithoutGuard: 'กำลังรันโดยไม่มี guardrail…',
  detectorsFired: 'Detector ที่ตรวจจับได้:',
  compareFooterTip: 'Tip: prompt ปกติจะเหมือนกันทั้งสองด้าน — ต่างกันเฉพาะเมื่อ guardrail ตรวจพบภัยคุกคาม',
  malicious: 'อันตราย',
  close: 'ปิด',

  // Guardrail overlay (provider name injected at render via {provider} token)
  guardrailResults: 'ผลตรวจ {provider}',
  noLakeraResult: 'ยังไม่มีผลตรวจ — ลองส่งข้อความใน chat ก่อน',
  flagged: 'พบความเสี่ยง',
  clean: 'ปลอดภัย',
  loadingResults: 'กำลังโหลดผลตรวจ…',
  guardrailsTriggered: 'Guardrails ทำงาน',
  allClear: 'ปลอดภัยทั้งหมด',
  noResult: 'ยังไม่มีผล',
  violationSummary: 'สรุปการละเมิด',
  guardrailDetails: 'รายละเอียด Guardrail',
  rawJson: 'JSON ดิบ',
  contentFlagged: 'เนื้อหาถูกตรวจพบ',
  contentFlaggedBody: 'เนื้อหานี้ถูกตรวจพบโดย {provider}',
  requestId: 'Request ID',
  refresh: 'รีเฟรช',
  detected: 'ตรวจพบ',
  clearStatus: 'ผ่าน',

  // Admin shell — ส่วน operator-facing แปลแค่ tab/header
  adminConsole: 'หน้าจัดการ',
  backToDemo: 'กลับหน้า Demo',
  tabSetup: 'ตั้งค่าเริ่มต้น',
  tabBranding: 'แบรนด์',
  tabLLM: 'LLM',
  tabRag: 'RAG',
  tabRagScanning: 'รายงานสแกน RAG',
  tabTools: 'คอนเนคเตอร์',
  tabSecurity: 'ความปลอดภัย',
  tabPrompts: 'Demo Prompts',
  tabExport: 'นำเข้า/ส่งออก',
};

export const LOCALES = { en: EN, th: TH };

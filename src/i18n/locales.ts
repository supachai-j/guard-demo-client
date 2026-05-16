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
  compareCtaTooltip: 'Run the same prompt with and without Lakera Guard, side by side',

  // Hero features
  feat1Title: 'AI-Powered Security',
  feat1Body: 'Advanced content moderation and guardrails powered by Lakera Guard.',
  feat2Title: 'Secure RAG System',
  feat2Body: 'AI-powered content for Lakera-protected intelligent responses.',
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
  compareTitle: 'Compare with vs. without Lakera Guard',
  compareSubtitle: 'Same prompt, same model — only the guardrail differs.',
  comparePromptPlaceholder: 'Type a prompt to test — try a malicious one to see Lakera block it.',
  compareQuickTest: 'Quick test:',
  compareRunning: 'Running both…',
  compareRun: 'Run comparison',
  withGuard: 'With Lakera Guard',
  withoutGuard: 'Without Guard',
  blocked: 'BLOCKED',
  allowed: 'ALLOWED',
  unfiltered: 'UNFILTERED',
  responsePlaceholder: 'Response will appear here.',
  runningWithGuard: 'Running with Guard…',
  runningWithoutGuard: 'Running without Guard…',
  detectorsFired: 'Detectors that fired:',
  compareFooterTip: 'Tip: a benign prompt should look the same on both sides — the panes only diverge when Lakera detects a threat.',
  malicious: 'malicious',
  close: 'Close',

  // Lakera overlay
  guardrailResults: 'Guardrail Results',
  noLakeraResult: 'No guardrail result available yet — send a chat message first.',
  flagged: 'Flagged',
  clean: 'Clean',
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
  compareCtaTooltip: 'รัน prompt เดียวกันคู่กัน เปิด Lakera Guard กับ ปิด',

  // Hero features
  feat1Title: 'ความปลอดภัยด้วย AI',
  feat1Body: 'ตรวจสอบเนื้อหาและตั้ง guardrails ด้วย Lakera Guard',
  feat2Title: 'ระบบ RAG ที่ปลอดภัย',
  feat2Body: 'สร้างเนื้อหาด้วย AI ตอบคำถามอย่างชาญฉลาดและถูกคุ้มครองด้วย Lakera',
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
  compareTitle: 'เปรียบเทียบเปิด vs ปิด Lakera Guard',
  compareSubtitle: 'Prompt เดียวกัน โมเดลเดียวกัน — ต่างกันแค่ guardrail',
  comparePromptPlaceholder: 'พิมพ์ prompt เพื่อทดสอบ — ลอง prompt อันตรายดูว่า Lakera บล็อกไหม',
  compareQuickTest: 'ลองทันที:',
  compareRunning: 'กำลังรันทั้งสองด้าน…',
  compareRun: 'เริ่มเปรียบเทียบ',
  withGuard: 'มี Lakera Guard',
  withoutGuard: 'ไม่มี Guard',
  blocked: 'บล็อก',
  allowed: 'อนุญาต',
  unfiltered: 'ไม่ผ่านการกรอง',
  responsePlaceholder: 'คำตอบจะแสดงตรงนี้',
  runningWithGuard: 'กำลังรันโดยมี Guard…',
  runningWithoutGuard: 'กำลังรันโดยไม่มี Guard…',
  detectorsFired: 'Detector ที่ตรวจจับได้:',
  compareFooterTip: 'Tip: prompt ปกติจะเหมือนกันทั้งสองด้าน — ต่างกันเฉพาะเมื่อ Lakera ตรวจพบภัยคุกคาม',
  malicious: 'อันตราย',
  close: 'ปิด',

  // Lakera overlay
  guardrailResults: 'ผลตรวจ Guardrail',
  noLakeraResult: 'ยังไม่มีผลตรวจ — ลองส่งข้อความใน chat ก่อน',
  flagged: 'พบความเสี่ยง',
  clean: 'ปลอดภัย',
};

export const LOCALES = { en: EN, th: TH };

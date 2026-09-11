/**
 * Drop Platform Email Templates
 *
 * Professional, fully responsive HTML email templates styled with Drop's exact
 * brand aesthetic (signature cyan/azure palette, crisp typography, and verified logo).
 */

export function escapeHtml(str: string): string {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const BRAND_LOGO_URL = "https://drop-water-delivery-website.vercel.app/brand/drop-logo-light.png";

function baseEmailWrapper(title: string, badgeText: string, contentHtml: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(title)}</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      background-color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      color: #0f172a;
      -webkit-font-smoothing: antialiased;
    }
    .wrapper {
      width: 100%;
      background-color: #f1f5f9;
      padding: 36px 12px;
    }
    .container {
      max-width: 580px;
      margin: 0 auto;
      background-color: #ffffff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04);
      border: 1px solid #e2e8f0;
    }
    .header {
      background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
      padding: 28px 32px;
      text-align: left;
    }
    .badge {
      display: inline-block;
      padding: 4px 12px;
      background-color: rgba(255, 255, 255, 0.18);
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      border-radius: 9999px;
      margin-bottom: 12px;
      border: 1px solid rgba(255, 255, 255, 0.3);
    }
    .title {
      color: #ffffff;
      font-size: 22px;
      font-weight: 800;
      margin: 0;
      letter-spacing: -0.02em;
    }
    .subtitle {
      color: rgba(255, 255, 255, 0.85);
      font-size: 13px;
      margin-top: 4px;
      margin-bottom: 0;
    }
    .content {
      padding: 32px;
    }
    .meta-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      margin-bottom: 24px;
      background-color: #f8fafc;
      border-radius: 12px;
      border: 1px solid #e2e8f0;
      overflow: hidden;
    }
    .meta-table tr:not(:last-child) td {
      border-bottom: 1px solid #e2e8f0;
    }
    .meta-label {
      padding: 12px 16px;
      font-size: 12px;
      font-weight: 600;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      width: 32%;
      vertical-align: top;
    }
    .meta-value {
      padding: 12px 16px;
      font-size: 14px;
      font-weight: 500;
      color: #0f172a;
      vertical-align: top;
    }
    .message-card {
      background-color: #ffffff;
      border-left: 4px solid #0284c7;
      border-top: 1px solid #e2e8f0;
      border-right: 1px solid #e2e8f0;
      border-bottom: 1px solid #e2e8f0;
      border-radius: 0 12px 12px 0;
      padding: 18px 20px;
      margin-bottom: 28px;
    }
    .message-text {
      font-size: 14px;
      line-height: 1.65;
      color: #334155;
      margin: 0;
      white-space: pre-wrap;
    }
    .action-btn {
      display: inline-block;
      background: #0284c7;
      color: #ffffff !important;
      text-decoration: none;
      font-size: 14px;
      font-weight: 600;
      padding: 12px 24px;
      border-radius: 10px;
      box-shadow: 0 4px 12px rgba(2, 132, 199, 0.25);
    }
    .footer {
      background-color: #f8fafc;
      padding: 20px 32px;
      border-top: 1px solid #e2e8f0;
      text-align: center;
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.6;
    }
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="header">
        <div style="margin-bottom: 16px;">
          <img src="${BRAND_LOGO_URL}" alt="Drop" height="30" style="height: 30px; width: auto; max-width: 140px; display: block; border: 0; background-color: #ffffff; padding: 4px 10px; border-radius: 8px;" />
        </div>
        <div class="badge">${escapeHtml(badgeText)}</div>
        <h1 class="title">${escapeHtml(title)}</h1>
        <p class="subtitle">Drop • Multivendor Water Delivery Platform</p>
      </div>
      <div class="content">
        ${contentHtml}
      </div>
      <div class="footer">
        <p style="margin: 0 0 6px 0;"><strong>Drop Technologies Ltd.</strong> • Nairobi, Kenya</p>
        <p style="margin: 0;">This automated notification was generated from <a href="https://drop-water-delivery-website.vercel.app" style="color: #0284c7; text-decoration: none;">drop-water-delivery-website.vercel.app</a></p>
      </div>
    </div>
  </div>
</body>
</html>`;
}

export interface ContactEmailData {
  name: string;
  email: string;
  phone?: string;
  category: string;
  subject?: string;
  message: string;
  submittedAt?: string;
}

export function renderContactInquiryEmail(data: ContactEmailData): { subject: string; html: string; text: string } {
  const timestamp = data.submittedAt || new Date().toLocaleString("en-KE", { timeZone: "Africa/Nairobi" });
  const subjectLine = `[DROP CONTACT] ${data.category}: ${data.name}${data.subject ? ` — ${data.subject}` : ""}`;

  const contentHtml = `
    <table class="meta-table">
      <tr>
        <td class="meta-label">From</td>
        <td class="meta-value"><strong>${escapeHtml(data.name)}</strong></td>
      </tr>
      <tr>
        <td class="meta-label">Email</td>
        <td class="meta-value"><a href="mailto:${escapeHtml(data.email)}" style="color: #0284c7; text-decoration: none;">${escapeHtml(data.email)}</a></td>
      </tr>
      ${data.phone ? `
      <tr>
        <td class="meta-label">Phone</td>
        <td class="meta-value">${escapeHtml(data.phone)}</td>
      </tr>` : ""}
      <tr>
        <td class="meta-label">Category</td>
        <td class="meta-value"><span style="display: inline-block; background-color: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 6px; font-weight: 600; font-size: 12px;">${escapeHtml(data.category)}</span></td>
      </tr>
      ${data.subject ? `
      <tr>
        <td class="meta-label">Subject</td>
        <td class="meta-value">${escapeHtml(data.subject)}</td>
      </tr>` : ""}
      <tr>
        <td class="meta-label">Submitted</td>
        <td class="meta-value" style="color: #64748b; font-size: 13px;">${escapeHtml(timestamp)} (EAT / Nairobi)</td>
      </tr>
    </table>

    <div style="font-size: 13px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">
      Inquiry Message:
    </div>
    <div class="message-card">
      <p class="message-text">${escapeHtml(data.message)}</p>
    </div>

    <div style="text-align: center; margin-top: 24px;">
      <a href="mailto:${escapeHtml(data.email)}?subject=Re:%20Drop%20Water%20Delivery%20Inquiry" class="action-btn">
        Reply to ${escapeHtml(data.name)}
      </a>
    </div>
  `;

  const textVersion = `
[DROP WEBSITE CONTACT INQUIRY]
------------------------------------------------------------
From:      ${data.name}
Email:     ${data.email}
Phone:     ${data.phone || "Not provided"}
Category:  ${data.category}
Subject:   ${data.subject || "General Inquiry"}
Timestamp: ${timestamp}
------------------------------------------------------------
Message:
${data.message}
------------------------------------------------------------
Reply directly to: ${data.email}
  `.trim();

  return {
    subject: subjectLine,
    html: baseEmailWrapper("New Website Inquiry", "Contact Form", contentHtml),
    text: textVersion,
  };
}

export interface InvestorEmailData {
  name: string;
  email: string;
  phone?: string;
  firmOrSyndicate?: string;
  inquiryType: "contact" | "schedule";
  ticketSize?: string;
  meetingPreference?: string;
  preferredTiming?: string;
  message: string;
  submittedAt?: string;
}

export function renderInvestorInquiryEmail(data: InvestorEmailData): { subject: string; html: string; text: string } {
  const timestamp = data.submittedAt || new Date().toLocaleString("en-KE", { timeZone: "Africa/Nairobi" });
  const firmStr = data.firmOrSyndicate ? ` (${data.firmOrSyndicate})` : "";
  const isSchedule = data.inquiryType === "schedule";
  const badge = isSchedule ? "🗓️ FOUNDER MEETING REQUEST" : "💼 INVESTOR INQUIRY";
  const subjectLine = `[DROP INVESTOR] ${isSchedule ? "Meeting Request" : "Inquiry"}: ${data.name}${firmStr}`;

  const contentHtml = `
    <div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; color: #1e40af; font-size: 13px;">
      <strong>${isSchedule ? "Founder Call Requested:" : "Investment Inquiry:"}</strong> 
      An investor has submitted a request via the Pitch Deck presentation page.
    </div>

    <table class="meta-table">
      <tr>
        <td class="meta-label">Investor Name</td>
        <td class="meta-value"><strong>${escapeHtml(data.name)}</strong></td>
      </tr>
      <tr>
        <td class="meta-label">Email</td>
        <td class="meta-value"><a href="mailto:${escapeHtml(data.email)}" style="color: #0284c7; text-decoration: none;">${escapeHtml(data.email)}</a></td>
      </tr>
      ${data.phone ? `
      <tr>
        <td class="meta-label">Phone / WhatsApp</td>
        <td class="meta-value">${escapeHtml(data.phone)}</td>
      </tr>` : ""}
      <tr>
        <td class="meta-label">Affiliation / Fund</td>
        <td class="meta-value"><strong>${escapeHtml(data.firmOrSyndicate || "Angel / Independent")}</strong></td>
      </tr>
      ${data.ticketSize ? `
      <tr>
        <td class="meta-label">Check Size Range</td>
        <td class="meta-value"><span style="display: inline-block; background-color: #dcfce7; color: #15803d; padding: 3px 10px; border-radius: 6px; font-weight: 700; font-size: 13px;">${escapeHtml(data.ticketSize)}</span></td>
      </tr>` : ""}
      ${data.meetingPreference ? `
      <tr>
        <td class="meta-label">Meeting Format</td>
        <td class="meta-value">${escapeHtml(data.meetingPreference)}</td>
      </tr>` : ""}
      ${data.preferredTiming ? `
      <tr>
        <td class="meta-label">Preferred Timing</td>
        <td class="meta-value">${escapeHtml(data.preferredTiming)}</td>
      </tr>` : ""}
      <tr>
        <td class="meta-label">Timestamp</td>
        <td class="meta-value" style="color: #64748b; font-size: 13px;">${escapeHtml(timestamp)} (EAT / Nairobi)</td>
      </tr>
    </table>

    <div style="font-size: 13px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">
      Investor Notes / Areas of Interest:
    </div>
    <div class="message-card">
      <p class="message-text">${escapeHtml(data.message || "No additional notes provided.")}</p>
    </div>

    <div style="text-align: center; margin-top: 24px;">
      <a href="mailto:${escapeHtml(data.email)}?subject=Drop%20Water%20Delivery%20%E2%80%94%20Founder%20Discussion" class="action-btn">
        Reply &amp; Schedule with ${escapeHtml(data.name)}
      </a>
    </div>
  `;

  const textVersion = `
[DROP INVESTOR PRESENTATION INQUIRY]
------------------------------------------------------------
Type:        ${isSchedule ? "Founder Meeting Request" : "General Investor Inquiry"}
Investor:    ${data.name}
Email:       ${data.email}
Phone:       ${data.phone || "Not provided"}
Affiliation: ${data.firmOrSyndicate || "Angel / Independent"}
Check Size:  ${data.ticketSize || "Not specified"}
Format:      ${data.meetingPreference || "Google Meet / Virtual"}
Timing:      ${data.preferredTiming || "Flexible"}
Timestamp:   ${timestamp}
------------------------------------------------------------
Notes / Questions:
${data.message || "None"}
------------------------------------------------------------
Reply directly to: ${data.email}
  `.trim();

  return {
    subject: subjectLine,
    html: baseEmailWrapper(isSchedule ? "Founder Call Request" : "Investor Inquiry", badge, contentHtml),
    text: textVersion,
  };
}

/**
 * Resend Email Service Client for Drop Website.
 *
 * Provides resilient, zero-dependency email delivery using Resend's REST API.
 * Gracefully logs to the server console if RESEND_API_KEY is not configured
 * so development, CI, and preview builds operate seamlessly without external keys.
 */

export interface SendEmailPayload {
  from?: string;
  to: string | string[];
  reply_to?: string;
  subject: string;
  html: string;
  text?: string;
  tags?: Array<{ name: string; value: string }>;
}

export interface SendEmailResult {
  success: boolean;
  id?: string;
  devMode?: boolean;
  error?: string;
}

const RESEND_API_URL = "https://api.resend.com/emails";

export async function sendEmail(payload: SendEmailPayload): Promise<SendEmailResult> {
  const apiKey = process.env.RESEND_API_KEY?.trim() || "";
  const defaultFrom = process.env.RESEND_FROM_EMAIL || "Drop <onboarding@resend.dev>";
  const from = payload.from || defaultFrom;
  const to = Array.isArray(payload.to) ? payload.to : [payload.to];

  // In development / missing API key mode, log cleanly and return simulated success
  if (!apiKey || apiKey.includes("PLACEHOLDER") || apiKey === "") {
    console.log("\n============================================================");
    console.log("📬 [DROP EMAIL SERVICE - DEV/LOGGING MODE]");
    console.log(`From:     ${from}`);
    console.log(`To:       ${to.join(", ")}`);
    console.log(`Reply-To: ${payload.reply_to || "None"}`);
    console.log(`Subject:  ${payload.subject}`);
    console.log("Tags:    ", payload.tags || []);
    console.log("------------------------------------------------------------");
    console.log("Content preview (first 300 chars):");
    console.log(payload.text || payload.html.replace(/<[^>]*>?/gm, " ").substring(0, 300) + "...");
    console.log("============================================================\n");

    return {
      success: true,
      id: `dev_${Date.now()}`,
      devMode: true,
    };
  }

  try {
    const response = await fetch(RESEND_API_URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from,
        to,
        reply_to: payload.reply_to,
        subject: payload.subject,
        html: payload.html,
        text: payload.text,
        tags: payload.tags,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      console.error("❌ Resend API Error:", data);
      return {
        success: false,
        error: data?.message || `HTTP ${response.status}: Failed to send email via Resend`,
      };
    }

    return {
      success: true,
      id: data.id,
      devMode: false,
    };
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    console.error("❌ Network exception sending email via Resend:", errorMessage);
    return {
      success: false,
      error: errorMessage,
    };
  }
}

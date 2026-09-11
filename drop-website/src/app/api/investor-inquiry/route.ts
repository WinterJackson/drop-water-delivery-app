import { NextRequest, NextResponse } from "next/server";
import { sendEmail } from "@/lib/resend";
import { renderInvestorInquiryEmail } from "@/lib/email-templates";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // Honeypot spam trap
    if (body.company_website) {
      console.warn("🛡️ Honeypot triggered in investor form — bot dropped.");
      return NextResponse.json({ success: true, message: "Inquiry received." });
    }

    const {
      name,
      email,
      phone,
      firmOrSyndicate,
      inquiryType,
      ticketSize,
      meetingPreference,
      preferredTiming,
      message,
    } = body;

    // Validation
    if (!name || typeof name !== "string" || name.trim().length < 2) {
      return NextResponse.json(
        { success: false, error: "Please enter your name." },
        { status: 400 }
      );
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email || typeof email !== "string" || !emailRegex.test(email.trim())) {
      return NextResponse.json(
        { success: false, error: "Please enter a valid email address." },
        { status: 400 }
      );
    }

    const receiverEmail = process.env.NOTIFICATION_RECEIVER_EMAIL || "winterjacksonwj@gmail.com";
    const type: "contact" | "schedule" = inquiryType === "schedule" ? "schedule" : "contact";

    // Render Drop branded HTML email for investors
    const emailData = renderInvestorInquiryEmail({
      name: name.trim(),
      email: email.trim(),
      phone: phone?.trim(),
      firmOrSyndicate: firmOrSyndicate?.trim() || "Angel / Independent",
      inquiryType: type,
      ticketSize: ticketSize?.trim(),
      meetingPreference: meetingPreference?.trim(),
      preferredTiming: preferredTiming?.trim(),
      message: message?.trim() || "Requested call via Pitch Deck presentation page.",
    });

    // Send via Resend
    const result = await sendEmail({
      to: receiverEmail,
      reply_to: email.trim(),
      subject: emailData.subject,
      html: emailData.html,
      text: emailData.text,
      tags: [
        { name: "type", value: "investor-inquiry" },
        { name: "intent", value: type },
      ],
    });

    if (!result.success) {
      return NextResponse.json(
        { success: false, error: result.error || "Failed to dispatch email. Please try again later." },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      message: type === "schedule"
        ? "Meeting request sent! Winter will follow up directly to confirm calendar availability."
        : "Thank you for reaching out! Winter will reply to your inquiry shortly.",
      devMode: result.devMode,
    });
  } catch (error: unknown) {
    const errorMsg = error instanceof Error ? error.message : "Internal Server Error";
    console.error("❌ Investor Inquiry API Handler Exception:", error);
    return NextResponse.json(
      { success: false, error: errorMsg },
      { status: 500 }
    );
  }
}

import { NextRequest, NextResponse } from "next/server";
import { sendEmail } from "@/lib/resend";
import { renderContactInquiryEmail } from "@/lib/email-templates";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // Honeypot spam protection: bots automatically fill hidden input fields
    if (body.website_url) {
      console.warn("🛡️ Honeypot triggered in contact form — spam detected and dropped.");
      return NextResponse.json({ success: true, message: "Inquiry received." });
    }

    const { name, email, phone, category, subject, message } = body;

    // Validation
    if (!name || typeof name !== "string" || name.trim().length < 2) {
      return NextResponse.json(
        { success: false, error: "Please provide your full name (at least 2 characters)." },
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

    if (!message || typeof message !== "string" || message.trim().length < 5) {
      return NextResponse.json(
        { success: false, error: "Please provide a message (at least 5 characters)." },
        { status: 400 }
      );
    }

    const receiverEmail = process.env.NOTIFICATION_RECEIVER_EMAIL || "winterjacksonwj@gmail.com";
    const selectedCategory = category?.trim() || "General Inquiry";

    // Render Drop branded HTML email
    const emailData = renderContactInquiryEmail({
      name: name.trim(),
      email: email.trim(),
      phone: phone?.trim(),
      category: selectedCategory,
      subject: subject?.trim(),
      message: message.trim(),
    });

    // Send via Resend with direct Reply-To
    const result = await sendEmail({
      to: receiverEmail,
      reply_to: email.trim(),
      subject: emailData.subject,
      html: emailData.html,
      text: emailData.text,
      tags: [
        { name: "type", value: "contact-form" },
        { name: "category", value: selectedCategory.toLowerCase().replace(/\s+/g, "-") },
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
      message: "Thank you! Your message has been received and Winter will follow up shortly.",
      devMode: result.devMode,
    });
  } catch (error: unknown) {
    const errorMsg = error instanceof Error ? error.message : "Internal Server Error";
    console.error("❌ Contact API Handler Exception:", error);
    return NextResponse.json(
      { success: false, error: errorMsg },
      { status: 500 }
    );
  }
}

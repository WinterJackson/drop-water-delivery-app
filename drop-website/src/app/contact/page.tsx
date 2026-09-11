"use client";

import { Button } from "@/components/ui/Button";
import { Mail, MapPin, CheckCircle2, AlertCircle, Loader2, Send } from "lucide-react";
import { useState } from "react";

const faqs = [
  {
    question: "Is Drop available in my area?",
    answer: "During our beta phase, Drop is operating in select neighborhoods in Nairobi, Kenya. We plan to expand rapidly after our official launch.",
  },
  {
    question: "How do I become a vendor?",
    answer: "If you own a water refilling station or distributorship, you can apply to join our vendor network through the 'Become a Vendor' page. Once approved, you can download the Vendor App and start receiving orders.",
  },
  {
    question: "How do I become a rider?",
    answer: "Independent riders with a motorcycle or bicycle can sign up via the 'Become a Rider' page. After a brief verification process, you'll be cleared to accept delivery requests.",
  },
  {
    question: "Is Drop free to use?",
    answer: "The Drop Customer app is free to download and use. You only pay for the water you order and a small delivery fee that goes to the rider.",
  },
  {
    question: "When will Drop officially launch?",
    answer: "We are finalizing our beta testing to ensure the best possible experience. We expect to officially launch in Q4 2026.",
  },
  {
    question: "How are payments handled?",
    answer: "All payments on the Drop platform are handled securely via M-Pesa. Customers pay upon delivery, and vendors/riders receive funds directly into their digital wallets.",
  },
];

const categories = [
  { value: "General Inquiry", label: "General Question" },
  { value: "Water Vendor Partnership", label: "Water Vendor Partnership" },
  { value: "Delivery Rider Network", label: "Delivery Rider Network" },
  { value: "Commercial Bulk Supply", label: "Commercial / Bulk Water Supply (B2B)" },
  { value: "Investor Inquiry", label: "Investor / Syndicate Inquiry" },
  { value: "Customer Support", label: "Customer Support & Beta Feedback" },
];

export default function ContactPage() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    category: "General Inquiry",
    subject: "",
    message: "",
    website_url: "", // Honeypot field for bot suppression
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errorMessage) setErrorMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const result = await response.json();

      if (!response.ok || !result.success) {
        throw new Error(result.error || "Failed to submit inquiry. Please try again.");
      }

      setIsSuccess(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setErrorMessage(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setFormData({
      name: "",
      email: "",
      phone: "",
      category: "General Inquiry",
      subject: "",
      message: "",
      website_url: "",
    });
    setIsSuccess(false);
    setErrorMessage(null);
  };

  return (
    <div className="bg-[var(--background)]">
      <div className="mx-auto max-w-[1100px] px-6 py-20 sm:py-28 lg:px-8">
        
        {/* Page header */}
        <div className="mx-auto max-w-2xl text-center mb-14">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-3.5 py-1 text-xs font-semibold text-[var(--accent)]">
            <Mail className="h-3.5 w-3.5" />
            DIRECT PLATFORM CONTACT
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl text-[var(--foreground)]">
            Get in Touch
          </h1>
          <p className="mt-4 text-base leading-7 text-[var(--foreground-muted)] sm:text-lg">
            Have questions about Drop, want to become a partner, or looking to join our early rollout? We respond quickly.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 lg:gap-14 mb-20">
          
          {/* Contact Form */}
          <div className="lg:col-span-3 bg-[var(--surface)] rounded-2xl p-6 sm:p-8 border border-[var(--border)] shadow-sm">
            <h2 className="text-xl font-bold mb-2 text-[var(--foreground)]">Send a Message</h2>
            <p className="text-sm text-[var(--foreground-muted)] mb-6">
              Fill out the details below and our team will receive your inquiry directly.
            </p>

            {errorMessage && (
              <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                <AlertCircle className="h-5 w-5 shrink-0 text-red-500" />
                <div>
                  <p className="font-semibold">Submission Error</p>
                  <p className="mt-0.5 text-xs text-red-700 dark:text-red-400">{errorMessage}</p>
                </div>
              </div>
            )}

            {isSuccess ? (
              <div className="flex flex-col items-center justify-center text-center py-10 h-full animate-fade-in-up">
                <div className="h-14 w-14 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mb-4 text-green-600 dark:text-green-400 shadow-sm">
                  <CheckCircle2 className="h-8 w-8" />
                </div>
                <h3 className="text-xl font-bold mb-2 text-[var(--foreground)]">Message Received!</h3>
                <p className="text-sm text-[var(--foreground-muted)] mb-6 max-w-sm">
                  Thank you for reaching out, <strong>{formData.name}</strong>. Your message has been routed to Winter Jackson and our operations team. We will get back to you shortly.
                </p>
                <Button onClick={handleReset} variant="outline" size="default">
                  Send Another Message
                </Button>
              </div>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit}>
                
                {/* Honeypot field (hidden from real users, catches automated bots) */}
                <div className="hidden" aria-hidden="true">
                  <label htmlFor="website_url">Website URL</label>
                  <input
                    type="text"
                    id="website_url"
                    name="website_url"
                    tabIndex={-1}
                    autoComplete="off"
                    value={formData.website_url}
                    onChange={handleChange}
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="name" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                      Full Name <span className="text-[var(--danger)]">*</span>
                    </label>
                    <input
                      type="text"
                      name="name"
                      id="name"
                      required
                      value={formData.name}
                      onChange={handleChange}
                      className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all"
                      placeholder="e.g. David Mwangi"
                    />
                  </div>

                  <div>
                    <label htmlFor="email" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                      Email Address <span className="text-[var(--danger)]">*</span>
                    </label>
                    <input
                      type="email"
                      name="email"
                      id="email"
                      required
                      value={formData.email}
                      onChange={handleChange}
                      className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all"
                      placeholder="david@example.com"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="phone" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                      Phone / WhatsApp <span className="text-xs font-normal text-[var(--foreground-muted)]">(Optional)</span>
                    </label>
                    <input
                      type="tel"
                      name="phone"
                      id="phone"
                      value={formData.phone}
                      onChange={handleChange}
                      className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all"
                      placeholder="+254 7..."
                    />
                  </div>

                  <div>
                    <label htmlFor="category" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                      Inquiry Category <span className="text-[var(--danger)]">*</span>
                    </label>
                    <select
                      id="category"
                      name="category"
                      required
                      value={formData.category}
                      onChange={handleChange}
                      className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all"
                    >
                      {categories.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label htmlFor="subject" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                    Subject <span className="text-xs font-normal text-[var(--foreground-muted)]">(Optional)</span>
                  </label>
                  <input
                    type="text"
                    name="subject"
                    id="subject"
                    value={formData.subject}
                    onChange={handleChange}
                    className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all"
                    placeholder="Brief summary of your inquiry"
                  />
                </div>

                <div>
                  <label htmlFor="message" className="block text-xs font-semibold uppercase tracking-wider text-[var(--foreground-muted)] mb-1.5">
                    Message <span className="text-[var(--danger)]">*</span>
                  </label>
                  <textarea
                    name="message"
                    id="message"
                    required
                    rows={4}
                    value={formData.message}
                    onChange={handleChange}
                    className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)] transition-all resize-y"
                    placeholder="Tell us what you need, questions about partnerships, or your location in Nairobi..."
                  />
                </div>

                <Button type="submit" size="lg" className="w-full gap-2 shadow-md" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Sending Inquiry...
                    </>
                  ) : (
                    <>
                      <Send className="h-4 w-4" />
                      Send Message
                    </>
                  )}
                </Button>
              </form>
            )}
          </div>

          {/* Direct Contact Info */}
          <div className="lg:col-span-2 flex flex-col justify-between gap-8">
            <div className="bg-[var(--surface-muted)] rounded-2xl p-6 border border-[var(--border)]">
              <h2 className="text-xl font-bold mb-3 text-[var(--foreground)]">Direct Communications</h2>
              <p className="text-sm leading-6 text-[var(--foreground-muted)] mb-6">
                Whether you run an existing water bottling station, manage an office needing bulk dispensers, or are an investor looking to partner, our lines are open.
              </p>

              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                    <Mail className="h-4 w-4 text-[var(--accent)]" />
                  </div>
                  <div>
                    <p className="text-xs text-[var(--foreground-muted)]">Founder &amp; Executive Email</p>
                    <a
                      href="mailto:winterjacksonwj@gmail.com"
                      className="text-sm font-semibold text-[var(--foreground)] hover:text-[var(--accent)] transition-colors"
                    >
                      winterjacksonwj@gmail.com
                    </a>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                    <MapPin className="h-4 w-4 text-[var(--accent)]" />
                  </div>
                  <div>
                    <p className="text-xs text-[var(--foreground-muted)]">Headquarters</p>
                    <p className="text-sm font-medium text-[var(--foreground)]">Nairobi, Kenya</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--accent)]/30 bg-[var(--accent)]/5 p-6">
              <h3 className="text-sm font-bold text-[var(--accent)] mb-1 uppercase tracking-wider">
                Investor Relations
              </h3>
              <p className="text-xs leading-5 text-[var(--foreground-muted)] mb-3">
                Review our pitch deck presentation and investment overview directly on the platform.
              </p>
              <a
                href="/pitch-deck"
                className="inline-flex text-xs font-bold text-[var(--accent)] hover:underline items-center gap-1"
              >
                View Pitch Deck &rarr;
              </a>
            </div>
          </div>
        </div>

        {/* FAQs */}
        <div className="border-t border-[var(--border)] pt-16">
          <h2 className="text-2xl font-bold text-center mb-10 text-[var(--foreground)]">
            Frequently Asked Questions
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto">
            {faqs.map((faq, index) => (
              <div
                key={index}
                className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm"
              >
                <h3 className="font-bold text-base mb-2 text-[var(--foreground)]">{faq.question}</h3>
                <p className="text-sm leading-relaxed text-[var(--foreground-muted)]">{faq.answer}</p>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

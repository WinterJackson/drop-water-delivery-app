"use client";

import { useState, useEffect } from "react";
import { X, Calendar, Mail, CheckCircle2, AlertCircle, Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface InvestorModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTab?: "contact" | "schedule";
}

const ticketSizeOptions = [
  { value: "Under $25k", label: "Under $25,000 (Individual Angel)" },
  { value: "$25k - $50k", label: "$25,000 – $50,000 (Standard Angel Ticket)" },
  { value: "$50k - $100k", label: "$50,000 – $100,000 (Syndicate / Co-Lead)" },
  { value: "$100k+", label: "$100,000+ (Lead Investor / Institutional)" },
  { value: "Exploring", label: "Exploring / General Advisory" },
];

const meetingFormatOptions = [
  { value: "Google Meet", label: "Google Meet (Virtual Video Call)" },
  { value: "Phone Call", label: "Phone / WhatsApp Audio Call" },
  { value: "In-Person Nairobi", label: "In-Person Meeting (Nairobi)" },
];

export function InvestorModal({ isOpen, onClose, initialTab = "schedule" }: InvestorModalProps) {
  const [selectedTab, setSelectedTab] = useState<"contact" | "schedule" | null>(null);
  const activeTab = selectedTab ?? initialTab;

  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    firmOrSyndicate: "",
    ticketSize: "$25k - $50k",
    meetingPreference: "Google Meet",
    preferredTiming: "",
    message: "",
    company_website: "", // Honeypot field
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Prevent background body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "unset";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errorMessage) setErrorMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/investor-inquiry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...formData,
          inquiryType: activeTab,
        }),
      });

      const result = await response.json();

      if (!response.ok || !result.success) {
        throw new Error(result.error || "Failed to submit request.");
      }

      setIsSuccess(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setErrorMessage(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetAndClose = () => {
    setIsSuccess(false);
    setErrorMessage(null);
    setSelectedTab(null);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-lg rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-6 sm:p-8 shadow-2xl z-10 my-8">
        
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 rounded-lg p-1.5 text-[var(--foreground-muted)] hover:bg-[var(--surface-muted)] hover:text-[var(--foreground)] transition-colors"
          aria-label="Close modal"
        >
          <X className="h-5 w-5" />
        </button>

        {/* Modal Header */}
        <div className="mb-6 pr-6">
          <span className="inline-block rounded-full bg-[var(--accent)]/10 text-[var(--accent)] px-3 py-1 text-xs font-bold uppercase tracking-wider mb-2">
            Pre-Seed Round • Angel Syndicate
          </span>
          <h2 className="text-2xl font-bold text-[var(--foreground)]">
            {activeTab === "schedule" ? "Schedule Founder Call" : "Contact Drop Founders"}
          </h2>
          <p className="text-xs text-[var(--foreground-muted)] mt-1">
            Connect directly with Winter Jackson (Founder &amp; Technical Lead)
          </p>
        </div>

        {/* Tabs */}
        {!isSuccess && (
          <div className="flex rounded-xl bg-[var(--surface-muted)] p-1 mb-6 border border-[var(--border)]">
            <button
              type="button"
              onClick={() => setSelectedTab("schedule")}
              className={`flex-1 py-2 text-xs font-bold rounded-lg flex items-center justify-center gap-1.5 transition-all ${
                activeTab === "schedule"
                  ? "bg-[var(--surface)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--foreground-muted)] hover:text-[var(--foreground)]"
              }`}
            >
              <Calendar className="h-3.5 w-3.5 text-[var(--accent)]" />
              Schedule Call
            </button>
            <button
              type="button"
              onClick={() => setSelectedTab("contact")}
              className={`flex-1 py-2 text-xs font-bold rounded-lg flex items-center justify-center gap-1.5 transition-all ${
                activeTab === "contact"
                  ? "bg-[var(--surface)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--foreground-muted)] hover:text-[var(--foreground)]"
              }`}
            >
              <Mail className="h-3.5 w-3.5 text-[var(--accent)]" />
              Direct Message
            </button>
          </div>
        )}

        {/* Success State */}
        {isSuccess ? (
          <div className="flex flex-col items-center justify-center text-center py-8 animate-fade-in-up">
            <div className="h-16 w-16 rounded-full bg-emerald-100 dark:bg-emerald-950/50 flex items-center justify-center mb-4 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-9 w-9" />
            </div>
            <h3 className="text-xl font-bold mb-2 text-[var(--foreground)]">
              {activeTab === "schedule" ? "Meeting Request Dispatched!" : "Inquiry Delivered!"}
            </h3>
            <p className="text-sm text-[var(--foreground-muted)] max-w-sm mb-6">
              Thank you, <strong>{formData.name}</strong>. Winter Jackson has received your notification at <code>winterjacksonwj@gmail.com</code> and will follow up with you directly.
            </p>
            <Button onClick={handleResetAndClose} size="default" className="w-full">
              Done
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            
            {/* Honeypot anti-spam */}
            <div className="hidden" aria-hidden="true">
              <input
                type="text"
                name="company_website"
                tabIndex={-1}
                autoComplete="off"
                value={formData.company_website}
                onChange={handleChange}
              />
            </div>

            {errorMessage && (
              <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
                <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
                <span>{errorMessage}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                  Your Name <span className="text-[var(--danger)]">*</span>
                </label>
                <input
                  type="text"
                  name="name"
                  required
                  value={formData.name}
                  onChange={handleChange}
                  placeholder="e.g. John Kamau"
                  className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                  Email <span className="text-[var(--danger)]">*</span>
                </label>
                <input
                  type="email"
                  name="email"
                  required
                  value={formData.email}
                  onChange={handleChange}
                  placeholder="john@example.com"
                  className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                  Syndicate / Fund / Angel Group
                </label>
                <input
                  type="text"
                  name="firmOrSyndicate"
                  value={formData.firmOrSyndicate}
                  onChange={handleChange}
                  placeholder="e.g. NaiBAN Angel / Independent"
                  className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                  Phone / WhatsApp <span className="font-normal">(Optional)</span>
                </label>
                <input
                  type="tel"
                  name="phone"
                  value={formData.phone}
                  onChange={handleChange}
                  placeholder="+254 7..."
                  className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                />
              </div>
            </div>

            {/* Schedule-specific options */}
            {activeTab === "schedule" && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                      Check Size Range
                    </label>
                    <select
                      name="ticketSize"
                      value={formData.ticketSize}
                      onChange={handleChange}
                      className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-xs bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                    >
                      {ticketSizeOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                      Meeting Format
                    </label>
                    <select
                      name="meetingPreference"
                      value={formData.meetingPreference}
                      onChange={handleChange}
                      className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-xs bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                    >
                      {meetingFormatOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                    Proposed Timing / Days Available
                  </label>
                  <input
                    type="text"
                    name="preferredTiming"
                    value={formData.preferredTiming}
                    onChange={handleChange}
                    placeholder="e.g. This Thursday morning or next Tuesday 2pm EAT"
                    className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none"
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-semibold text-[var(--foreground-muted)] mb-1">
                {activeTab === "schedule" ? "Discussion Focus & Notes" : "Your Message"}
              </label>
              <textarea
                name="message"
                rows={3}
                value={formData.message}
                onChange={handleChange}
                placeholder={
                  activeTab === "schedule"
                    ? "Topics to cover, data room access request, or questions regarding unit economics..."
                    : "Enter your message or questions for the founders..."
                }
                className="w-full rounded-xl border border-[var(--border)] py-2 px-3 text-sm bg-[var(--background)] text-[var(--foreground)] focus:ring-2 focus:ring-[var(--ring)] focus:outline-none resize-none"
              />
            </div>

            <Button
              type="submit"
              size="default"
              disabled={isSubmitting}
              className="w-full gap-2 mt-2 bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90 shadow-md"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Routing to Founders...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  {activeTab === "schedule" ? "Confirm & Request Call" : "Send Inquiry"}
                </>
              )}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}

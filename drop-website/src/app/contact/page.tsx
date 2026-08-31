"use client";

import { Button } from "@/components/ui/Button";
import { Mail, MapPin, CheckCircle2 } from "lucide-react";
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

export default function ContactPage() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    // Simulate network request for waitlist signup
    await new Promise((resolve) => setTimeout(resolve, 1500));
    
    setIsSubmitting(false);
    setIsSuccess(true);
  };

  return (
    <div className="bg-[var(--background)]">
      <div className="mx-auto max-w-[1100px] px-6 py-20 sm:py-28 lg:px-8">
        
        {/* Page header */}
        <div className="mx-auto max-w-2xl text-center mb-14">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">Contact &amp; Early Access</h1>
          <p className="mt-4 text-base leading-7 text-[var(--foreground-muted)] sm:text-lg">
            Have questions? Want to be notified when we launch in your area? Get in touch.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-10 lg:gap-14 mb-20">
          {/* Contact Form — wider */}
          <div className="lg:col-span-3 bg-[var(--surface)] rounded-2xl p-6 sm:p-8 border border-[var(--border)] shadow-sm">
            <h2 className="text-xl font-bold mb-5">Join the Waitlist</h2>
            {isSuccess ? (
              <div className="flex flex-col items-center justify-center text-center py-10 h-full">
                <div className="h-12 w-12 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center mb-4 text-green-600 dark:text-green-400">
                  <CheckCircle2 className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-bold mb-2">You&apos;re on the list!</h3>
                <p className="text-sm text-[var(--foreground-muted)] mb-6">
                  Thank you for your interest. We&apos;ll notify you as soon as we launch in your area.
                </p>
                <Button onClick={() => setIsSuccess(false)} variant="outline">Sign up another user</Button>
              </div>
            ) : (
              <form className="space-y-5" onSubmit={handleSubmit}>
                <div>
                  <label htmlFor="name" className="block text-sm font-medium mb-1.5">Full Name</label>
                  <input
                    type="text"
                    name="name"
                    id="name"
                    required
                    className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                    placeholder="John Doe"
                  />
                </div>
                
                <div>
                  <label htmlFor="email" className="block text-sm font-medium mb-1.5">Email Address</label>
                  <input
                    type="email"
                    name="email"
                    id="email"
                    required
                    className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] placeholder:text-[var(--foreground-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                    placeholder="john@example.com"
                  />
                </div>

                <div>
                  <label htmlFor="role" className="block text-sm font-medium mb-1.5">I am interested as a...</label>
                  <select
                    id="role"
                    name="role"
                    required
                    className="block w-full rounded-xl border border-[var(--border)] py-2.5 px-4 text-sm bg-[var(--background)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                  >
                    <option value="Customer">Customer</option>
                    <option value="Vendor">Water Vendor</option>
                    <option value="Rider">Delivery Rider</option>
                  </select>
                </div>

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? "Signing up..." : "Sign Up for Early Access"}
                </Button>
              </form>
            )}
          </div>

          {/* Direct Contact Info */}
          <div className="lg:col-span-2 flex flex-col justify-center gap-8">
            <div>
              <h2 className="text-xl font-bold mb-3">Get in Touch</h2>
              <p className="text-sm leading-7 text-[var(--foreground-muted)]">
                We&apos;re always looking for feedback, partnerships, and talented individuals to join our mission of solving water delivery in Kenya.
              </p>
            </div>
            
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                  <Mail className="h-4 w-4 text-[var(--accent)]" />
                </div>
                <div>
                  <p className="text-xs text-[var(--foreground-muted)]">Email</p>
                  <a href="mailto:hello@dropwater.co.ke" className="text-sm font-medium text-[var(--foreground)] hover:text-[var(--accent)] transition-colors">hello@dropwater.co.ke</a>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                  <MapPin className="h-4 w-4 text-[var(--accent)]" />
                </div>
                <div>
                  <p className="text-xs text-[var(--foreground-muted)]">Location</p>
                  <p className="text-sm font-medium">Nairobi, Kenya</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* FAQ Section */}
        <div className="mx-auto max-w-3xl mt-8">
          <h2 className="text-2xl font-bold tracking-tight text-center mb-10">Frequently Asked Questions</h2>
          <div className="space-y-4">
            {faqs.map((faq) => (
              <div key={faq.question} className="p-5 bg-[var(--surface)] rounded-xl border border-[var(--border)]">
                <h3 className="text-sm font-semibold leading-6">{faq.question}</h3>
                <p className="mt-1.5 text-sm leading-6 text-[var(--foreground-muted)]">{faq.answer}</p>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

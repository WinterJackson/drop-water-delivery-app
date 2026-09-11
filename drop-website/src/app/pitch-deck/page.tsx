import { Metadata } from "next";
import Link from "next/link";
import { Download, ExternalLink, Mail, ShieldCheck, TrendingUp, Layers, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";

export const metadata: Metadata = {
  title: "Investor Pitch Deck | Drop — Water Delivery Platform",
  description: "Official pitch deck and investor presentation for Drop, Kenya's premier multivendor water delivery platform.",
};

export default function PitchDeckPage() {
  return (
    <div className="bg-[var(--background)] min-h-screen py-16 sm:py-24">
      <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-8 border-b border-[var(--border)]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-3.5 py-1 text-xs font-semibold text-[var(--accent)] mb-3">
              <ShieldCheck className="h-3.5 w-3.5" />
              INVESTOR PRESENTATION • PRE-SEED
            </div>
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl text-[var(--foreground)]">
              Drop Pitch Deck
            </h1>
            <p className="mt-2 text-base text-[var(--foreground-muted)] max-w-xl">
              Transforming urban water delivery and reverse-logistics infrastructure across Kenya.
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-3">
            <a 
              href="/pitch-deck.pdf" 
              download="Drop_Pitch_Deck.pdf"
              className="inline-flex"
            >
              <Button size="default" className="gap-2 bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90 shadow-md">
                <Download className="h-4 w-4" />
                Download PDF
              </Button>
            </a>
            <a 
              href="/pitch-deck.pdf" 
              target="_blank" 
              rel="noopener noreferrer"
              className="inline-flex"
            >
              <Button size="default" variant="outline" className="gap-2 border-[var(--border)] hover:bg-[var(--surface-muted)]">
                <ExternalLink className="h-4 w-4" />
                Open Fullscreen
              </Button>
            </a>
            <a 
              href="mailto:winterjacksonwj@gmail.com?subject=Drop%20Investment%20Inquiry%20(NaiBAN)"
              className="inline-flex"
            >
              <Button size="default" variant="outline" className="gap-2 bg-[var(--surface-muted)] hover:bg-[var(--surface-raised)] border border-[var(--border)]">
                <Mail className="h-4 w-4" />
                Contact Founders
              </Button>
            </a>
          </div>
        </div>

        {/* Investment Highlights Strip */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 my-8">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)] uppercase tracking-wider mb-1">
              <TrendingUp className="h-4 w-4" /> Market Opportunity
            </div>
            <div className="text-lg font-bold text-[var(--foreground)]">Nairobi, Kenya</div>
            <p className="text-xs text-[var(--foreground-muted)] mt-1">High-frequency recurring utility with 90%+ natural retention</p>
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)] uppercase tracking-wider mb-1">
              <Layers className="h-4 w-4" /> Revenue Model
            </div>
            <div className="text-lg font-bold text-[var(--foreground)]">Dual Marketplace</div>
            <p className="text-xs text-[var(--foreground-muted)] mt-1">5% vendor take + fixed service fees + delivery spread</p>
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)] uppercase tracking-wider mb-1">
              <ShieldCheck className="h-4 w-4" /> Core Moat
            </div>
            <div className="text-lg font-bold text-[var(--foreground)]">Bottle Float Ledger</div>
            <p className="text-xs text-[var(--foreground-muted)] mt-1">Solves 20L container shrinkage and reverse logistics</p>
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--accent)] uppercase tracking-wider mb-1">
              <CheckCircle2 className="h-4 w-4" /> Platform Readiness
            </div>
            <div className="text-lg font-bold text-[var(--foreground)]">Live in Beta</div>
            <p className="text-xs text-[var(--foreground-muted)] mt-1">3 Mobile apps + Operations Console + M-Pesa automated</p>
          </div>
        </div>

        {/* Embedded PDF Viewer */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] overflow-hidden shadow-xl mb-12">
          <div className="flex items-center justify-between px-4 py-3 bg-[var(--surface-muted)] border-b border-[var(--border)] text-xs text-[var(--foreground-muted)]">
            <div className="flex items-center gap-2">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              <span className="font-medium text-[var(--foreground)]">Drop_Pitch_Deck.pdf</span>
            </div>
            <div className="flex items-center gap-4">
              <span>827 KB • PDF Document</span>
              <a 
                href="/pitch-deck.pdf" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-[var(--accent)] hover:underline flex items-center gap-1"
              >
                Pop out <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </div>

          {/* Interactive Document Viewer */}
          <div className="relative w-full h-[720px] bg-[var(--background)]">
            <iframe 
              src="/pitch-deck.pdf#toolbar=1&navpanes=0" 
              className="w-full h-full border-0"
              title="Drop Investor Pitch Deck"
            />
          </div>
        </div>

        {/* Bottom CTA for Investors */}
        <div className="rounded-2xl bg-[var(--surface-muted)] border border-[var(--border)] p-8 text-center sm:text-left sm:flex items-center justify-between gap-6">
          <div>
            <h3 className="text-xl font-bold text-[var(--foreground)]">Interested in participating in Drop&apos;s round?</h3>
            <p className="text-sm text-[var(--foreground-muted)] mt-1">
              We welcome strategic angel investors, syndicates, and ecosystem partners.
            </p>
          </div>
          <div className="mt-4 sm:mt-0 flex flex-wrap gap-3 shrink-0">
            <Link href="/apps">
              <Button size="default" variant="outline">
                Test Beta Apps
              </Button>
            </Link>
            <a href="mailto:winterjacksonwj@gmail.com?subject=Drop%20Investment%20Inquiry%20(NaiBAN)">
              <Button size="default" className="bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90">
                Schedule Founder Call
              </Button>
            </a>
          </div>
        </div>

      </div>
    </div>
  );
}

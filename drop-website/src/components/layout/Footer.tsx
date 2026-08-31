import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

export function Footer() {
  return (
    <div className="brand-chrome mt-auto bg-[var(--background)] pl-[var(--chrome-inset)] pt-[var(--chrome-inset)] pb-[var(--chrome-inset)]">
      <footer className="rounded-l-[40px] bg-[var(--chrome)] text-[var(--chrome-foreground)] py-12 sm:py-16">
      <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-4 lg:gap-12">
          {/* Brand */}
          <div className="col-span-2 sm:col-span-1 flex flex-col gap-4">
            <Logo href="/" height={22} className="w-fit rounded-lg bg-[var(--surface)] px-2 py-1.5" />
            <p className="text-sm leading-6 text-white/85">
              Clean Water, Delivered to Your Door. Kenya&apos;s premier multivendor water delivery marketplace.
            </p>
          </div>
          
          {/* Platform */}
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-white">Platform</h3>
            <ul className="flex flex-col gap-2.5">
              <li><Link href="/apps" className="text-sm text-white/85 transition-colors hover:text-white">Download the Apps</Link></li>
              <li><Link href="/become-a-vendor" className="text-sm text-white/85 transition-colors hover:text-white">Become a Vendor</Link></li>
              <li><Link href="/become-a-rider" className="text-sm text-white/85 transition-colors hover:text-white">Drive with Drop</Link></li>
            </ul>
          </div>

          {/* Company */}
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-white">Company</h3>
            <ul className="flex flex-col gap-2.5">
              <li><Link href="/about" className="text-sm text-white/85 transition-colors hover:text-white">About Us</Link></li>
              <li><Link href="/contact" className="text-sm text-white/85 transition-colors hover:text-white">Contact</Link></li>
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-white">Legal</h3>
            <ul className="flex flex-col gap-2.5">
              <li><Link href="/terms" className="text-sm text-white/85 transition-colors hover:text-white">Terms of Service</Link></li>
              <li><Link href="/privacy" className="text-sm text-white/85 transition-colors hover:text-white">Privacy Policy</Link></li>
            </ul>
          </div>
        </div>
        
        <div className="mt-10 border-t border-[var(--chrome-edge)] pt-8 text-center text-xs text-white/70">
          <p>&copy; {new Date().getFullYear()} Drop Water Delivery. All rights reserved.</p>
        </div>
      </div>
      </footer>
    </div>
  );
}

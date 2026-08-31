import { Button } from "@/components/ui/Button";
import Image from "next/image";
import { Download, AlertTriangle } from "lucide-react";

export default function AppsPage() {
  return (
    <div className="bg-[var(--background)]">
      <div className="mx-auto max-w-[1100px] px-6 py-20 sm:py-28 lg:px-8">
        
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-8 items-center mb-20">
          {/* Page header */}
          <div className="text-left">
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">Download the Beta</h1>
            <p className="mt-4 text-base leading-7 text-[var(--foreground-muted)] sm:text-lg max-w-lg">
              Drop is currently in beta. Download the Android APKs below to experience the platform.
            </p>
          </div>

          {/* Beta Credentials Card */}
          <div className="w-full">
            <div className="glass-card overflow-hidden rounded-2xl p-6 sm:p-8 relative">
            <div className="absolute top-4 right-4">
              <AlertTriangle className="h-5 w-5 text-[var(--warning)]" />
            </div>
            <h2 className="text-xl font-bold mb-5">🧪 Beta Test Credentials</h2>
            <div className="rounded-xl p-5 border border-[var(--border)] bg-[var(--surface-muted)] font-mono text-sm">
              <p className="mb-1.5 font-semibold">Password for all accounts: <span className="text-[var(--accent)]">Drop2026!!</span></p>
              <p className="mb-5 text-[var(--foreground-muted)]">Verification code (if prompted): <span className="text-[var(--accent)]">424242</span></p>

              <div className="space-y-3.5">
                <div>
                  <h3 className="font-bold text-sm">Customer App</h3>
                  <p className="text-[var(--foreground-muted)] text-xs mt-0.5">customer+clerk_test@example.com</p>
                </div>
                <div>
                  <h3 className="font-bold text-sm">Rider App</h3>
                  <p className="text-[var(--foreground-muted)] text-xs mt-0.5">rider+clerk_test@example.com</p>
                </div>
                <div>
                  <h3 className="font-bold text-sm">Vendor App (Retail)</h3>
                  <p className="text-[var(--foreground-muted)] text-xs mt-0.5">vendor-retail+clerk_test@example.com</p>
                </div>
                <div>
                  <h3 className="font-bold text-sm">Vendor App (Wholesale)</h3>
                  <p className="text-[var(--foreground-muted)] text-xs mt-0.5">vendor-wholesale+clerk_test@example.com</p>
                </div>
              </div>
            </div>
            <p className="mt-4 text-xs text-[var(--foreground-muted)]">
              Note: These are isolated development accounts. No real transactions will occur.
            </p>
          </div>
          </div>
        </div>

        {/* App Download Cards */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3 lg:gap-8">
          
          {/* Customer App */}
          <div className="flex flex-col items-center rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-7 shadow-sm text-center">
            <div className="h-24 w-24 relative mb-5">
              <Image src="/dropy/dropy_search.webp" alt="Customer App" fill className="object-contain" />
            </div>
            <h3 className="text-lg font-bold mb-1.5">Drop Customer</h3>
            <p className="text-sm text-[var(--foreground-muted)] mb-6 flex-1 leading-relaxed">
              Order water from local vendors, track deliveries, and pay securely.
            </p>
            <Button disabled className="w-full">
              <Download className="mr-2 h-4 w-4" /> Coming Soon (APK)
            </Button>
          </div>

          {/* Vendor App */}
          <div className="flex flex-col items-center rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-7 shadow-sm text-center">
            <div className="h-24 w-24 relative mb-5">
              <Image src="/dropy/dropy_celebrate.webp" alt="Vendor App" fill className="object-contain" />
            </div>
            <h3 className="text-lg font-bold mb-1.5">Drop Vendor</h3>
            <p className="text-sm text-[var(--foreground-muted)] mb-6 flex-1 leading-relaxed">
              Manage your storefront, accept orders, and dispatch riders.
            </p>
            <Button disabled className="w-full">
              <Download className="mr-2 h-4 w-4" /> Coming Soon (APK)
            </Button>
          </div>

          {/* Rider App */}
          <div className="flex flex-col items-center rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-7 shadow-sm text-center">
            <div className="h-24 w-24 relative mb-5">
              <Image src="/dropy/dropy_hero.webp" alt="Rider App" fill className="object-contain" />
            </div>
            <h3 className="text-lg font-bold mb-1.5">Drop Rider</h3>
            <p className="text-sm text-[var(--foreground-muted)] mb-6 flex-1 leading-relaxed">
              Accept deliveries, navigate efficiently, and earn on your schedule.
            </p>
            <Button disabled className="w-full">
              <Download className="mr-2 h-4 w-4" /> Coming Soon (APK)
            </Button>
          </div>

        </div>
        
        {/* Installation Instructions */}
        <div className="mx-auto max-w-2xl mt-20">
          <h2 className="text-xl font-bold mb-5 text-center">How to Install Android APKs</h2>
          <ol className="list-decimal list-inside space-y-3 text-sm leading-6 text-[var(--foreground-muted)] bg-[var(--surface-muted)] p-6 sm:p-8 rounded-2xl border border-[var(--border)]">
            <li>Download the desired APK file to your Android device using the links above.</li>
            <li>Open your device <strong className="text-[var(--foreground)]">Settings</strong> &gt; <strong className="text-[var(--foreground)]">Security</strong> (or Privacy).</li>
            <li>Enable <strong className="text-[var(--foreground)]">Install from Unknown Sources</strong> (or give your browser permission to install apps).</li>
            <li>Locate the downloaded APK file in your Downloads folder and tap to install.</li>
            <li>Open the app and log in using the Beta Test credentials provided above.</li>
          </ol>
        </div>

      </div>
    </div>
  );
}

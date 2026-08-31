export default function TermsPage() {
  return (
    <div className="bg-[var(--background)]">
      {/* Header banner */}
      <section className="bg-[var(--chrome)] py-14 sm:py-16 text-center">
        <div className="mx-auto max-w-[1100px] px-6">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Terms of Service</h1>
          <p className="mt-2 text-sm text-white/70">Last updated: August 2026</p>
        </div>
      </section>

      <div className="mx-auto max-w-[1100px] px-6 py-14 sm:py-20 lg:px-8">
        <div className="space-y-8">
          <p className="text-sm leading-7 text-[var(--foreground-muted)]">
            Please read these Terms of Service carefully before using the Drop Water Delivery platform.
          </p>

          <div>
            <h2 className="text-lg font-bold mb-3">1. Acceptance of Terms</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              By accessing or using our platform, you agree to be bound by these Terms. If you disagree with any part of the terms, then you may not access the service. Currently, the service is in a Beta phase, and all interactions should be treated as such.
            </p>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">2. Description of Service</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              Drop is a multivendor marketplace that connects independent water vendors and independent delivery riders with end customers. We provide the technology platform to facilitate these transactions but we do not sell water directly, nor do we employ the riders.
            </p>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">3. User Accounts</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              When you create an account with us, you must provide information that is accurate, complete, and current at all times. Failure to do so constitutes a breach of the Terms, which may result in immediate termination of your account on our platform.
            </p>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">4. Vendor and Rider Responsibilities</h2>
            <ul className="list-disc pl-5 space-y-2 text-sm leading-7 text-[var(--foreground-muted)]">
              <li><strong className="text-[var(--foreground)]">Vendors:</strong> Must ensure that all water sold meets KEBS safety standards and is accurately represented.</li>
              <li><strong className="text-[var(--foreground)]">Riders:</strong> Must maintain a valid license, obey all traffic laws, and handle deliveries professionally.</li>
            </ul>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">5. Limitation of Liability</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              In no event shall Drop Water Delivery, nor its directors, employees, partners, agents, suppliers, or affiliates, be liable for any indirect, incidental, special, consequential or punitive damages, including without limitation, loss of profits, data, use, goodwill, or other intangible losses, resulting from your access to or use of or inability to access or use the platform.
            </p>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">6. Contact</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">If you have any questions about these Terms, please contact us at:</p>
            <p className="mt-2 text-sm font-semibold">
              <a href="mailto:legal@dropwater.co.ke" className="text-[var(--accent)] hover:underline">legal@dropwater.co.ke</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

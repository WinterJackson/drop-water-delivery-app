export default function PrivacyPage() {
  return (
    <div className="bg-[var(--background)]">
      {/* Header banner */}
      <section className="bg-[var(--chrome)] py-14 sm:py-16 text-center">
        <div className="mx-auto max-w-[1100px] px-6">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Privacy Policy</h1>
          <p className="mt-2 text-sm text-white/70">Last updated: August 2026</p>
        </div>
      </section>

      <div className="mx-auto max-w-[1100px] px-6 py-14 sm:py-20 lg:px-8">
        <div className="space-y-8">
          <p className="text-sm leading-7 text-[var(--foreground-muted)]">
            At Drop Water Delivery, we take your privacy seriously. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you visit our website or use our mobile applications (Customer, Vendor, and Rider apps).
          </p>

          <div>
            <h2 className="text-lg font-bold mb-3">1. Information We Collect</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)] mb-3">We may collect information about you in a variety of ways. The information we may collect includes:</p>
            <ul className="list-disc pl-5 space-y-2 text-sm leading-7 text-[var(--foreground-muted)]">
              <li><strong className="text-[var(--foreground)]">Personal Data:</strong> Personally identifiable information, such as your name, delivery address, email address, and telephone number.</li>
              <li><strong className="text-[var(--foreground)]">Location Data:</strong> We may request access or permission to track location-based information from your mobile device to provide delivery tracking services.</li>
              <li><strong className="text-[var(--foreground)]">Financial Data:</strong> Financial information related to your M-Pesa transactions. Note that we do not store full payment credentials on our servers.</li>
            </ul>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">2. Use of Your Information</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)] mb-3">Having accurate information about you permits us to provide you with a smooth, efficient, and customized experience. Specifically, we may use information collected about you via the application to:</p>
            <ul className="list-disc pl-5 space-y-2 text-sm leading-7 text-[var(--foreground-muted)]">
              <li>Facilitate water delivery orders between customers, vendors, and riders.</li>
              <li>Process payments and refunds.</li>
              <li>Monitor delivery routes and provide real-time tracking.</li>
              <li>Respond to customer service requests and support needs.</li>
            </ul>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">3. Disclosure of Your Information</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              We may share information we have collected about you in certain situations. Your information may be disclosed to vendors and riders specifically for the purpose of fulfilling your water delivery order. We do not sell your personal data to third parties.
            </p>
          </div>

          <div>
            <h2 className="text-lg font-bold mb-3">4. Contact Us</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">If you have questions or comments about this Privacy Policy, please contact us at:</p>
            <p className="mt-2 text-sm font-semibold">
              <a href="mailto:privacy@dropwater.co.ke" className="text-[var(--accent)] hover:underline">privacy@dropwater.co.ke</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

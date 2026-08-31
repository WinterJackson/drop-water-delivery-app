import Image from "next/image";

export default function AboutPage() {
  return (
    <div className="bg-[var(--background)]">
      {/* Hero banner */}
      <section className="bg-[var(--chrome)] py-16 sm:py-20 text-center">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl lg:text-5xl">About Drop</h1>
          <p className="mt-4 text-base text-white/85 sm:text-lg max-w-xl mx-auto leading-relaxed">
            Our mission is to make clean water accessible to every household in Kenya through a transparent, reliable, and efficient multivendor marketplace.
          </p>
        </div>
      </section>

      <div className="mx-auto max-w-[1100px] px-6 py-16 sm:py-20 lg:px-8">
        {/* Mascot */}
        <div className="flex justify-center mb-12">
          <Image
            src="/dropy/dropy_search.webp"
            alt="Dropy thinking"
            width={120}
            height={120}
            className="drop-shadow-lg"
          />
        </div>

        <div className="space-y-10">
          <div>
            <h2 className="text-xl font-bold mb-3">The Problem</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              Water delivery in Kenya is currently fragmented, unreliable, and lacks transparency. Customers often struggle to find consistent suppliers, compare prices, or track when their delivery will actually arrive.
            </p>
          </div>

          <div>
            <h2 className="text-xl font-bold mb-3">Our Solution</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              Drop is a unified platform connecting customers directly with local water vendors and independent riders. We provide the digital infrastructure for vendors to manage their businesses, riders to earn flexibly, and customers to order with confidence.
            </p>
          </div>

          <div>
            <h2 className="text-xl font-bold mb-3">How it Works</h2>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              As a multivendor marketplace, Drop does not own the water or the delivery vehicles. Instead, we empower local entrepreneurs. Vendors list their products on our platform, customers place orders, and independent riders fulfill the deliveries. Every transaction is secured via M-Pesa, and every delivery is tracked in real-time via GPS.
            </p>
          </div>

          <div className="p-6 sm:p-8 rounded-2xl bg-[var(--surface-muted)] border border-[var(--border)]">
            <h3 className="text-lg font-bold mb-2">Current Stage: Beta Testing</h3>
            <p className="text-sm leading-7 text-[var(--foreground-muted)]">
              We are currently in the pre-launch phase. The Drop platform (including Customer, Vendor, and Rider mobile apps) is built and undergoing rigorous beta testing to ensure a flawless experience when we officially launch to the public.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

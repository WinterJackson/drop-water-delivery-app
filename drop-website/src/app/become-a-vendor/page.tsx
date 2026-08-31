import { Button } from "@/components/ui/Button";
import Link from "next/link";
import { Store, TrendingUp, ShieldCheck, Wallet } from "lucide-react";

const benefits = [
  {
    title: "Reach More Customers",
    description: "Tap into our growing user base. We handle the marketing, you handle the water.",
    icon: TrendingUp,
  },
  {
    title: "Digital Storefront",
    description: "Manage your inventory, set prices, and view sales analytics all from your phone.",
    icon: Store,
  },
  {
    title: "Secure Payments",
    description: "No more chasing cash or handling fake M-Pesa messages. Payments settle instantly to your Drop Wallet.",
    icon: Wallet,
  },
  {
    title: "Zero-Fraud Float Protection",
    description: "Our closed-loop float tracking system ensures you never lose empty bottles again.",
    icon: ShieldCheck,
  },
];

export default function BecomeVendorPage() {
  return (
    <div className="bg-[var(--background)]">
      {/* Hero Section */}
      <section className="py-16 sm:py-24 bg-[var(--chrome)] text-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/15" />
        <div className="relative mx-auto max-w-[1100px] px-6 lg:px-8">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl lg:text-5xl mb-5">
            Grow your water business with Drop
          </h1>
          <p className="text-base text-white/85 sm:text-lg max-w-xl mx-auto mb-8 leading-relaxed">
            Join Kenya&apos;s first dedicated multivendor water marketplace. Digitize your operations, increase your sales, and let independent riders handle the delivery.
          </p>
          <Link href="/contact">
            <Button size="lg" className="bg-white text-[var(--accent)] font-bold px-8 shadow-lg hover:bg-white/90 hover:shadow-xl">
              Apply to become a Vendor
            </Button>
          </Link>
        </div>
      </section>

      {/* Benefits */}
      <section className="py-20 sm:py-28">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <h2 className="text-2xl font-bold text-center mb-12">Why partner with Drop?</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 lg:gap-8">
            {benefits.map((benefit) => (
              <div key={benefit.title} className="flex gap-5 p-6 rounded-2xl bg-[var(--surface)] border border-[var(--border)] shadow-sm transition-shadow hover:shadow-md">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                  <benefit.icon className="h-6 w-6 text-[var(--accent)]" />
                </div>
                <div>
                  <h3 className="text-base font-bold mb-1.5">{benefit.title}</h3>
                  <p className="text-sm leading-6 text-[var(--foreground-muted)]">{benefit.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Requirements */}
      <section className="py-20 sm:py-28 bg-[var(--surface-muted)]">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <h2 className="text-2xl font-bold mb-10 text-center">What you need to get started</h2>
          <ul className="space-y-5">
            {[
              { num: "1", title: "A registered water business", desc: "You must have a physical shop or distribution point in our operating areas." },
              { num: "2", title: "KEBS Certification", desc: "Quality is our priority. Your water must meet Kenya Bureau of Standards requirements." },
              { num: "3", title: "An Android Smartphone", desc: "To run the Drop Vendor app, receive orders, and track your business." },
            ].map((item) => (
              <li key={item.num} className="flex items-start gap-4">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-white text-sm font-bold">
                  {item.num}
                </div>
                <div>
                  <h4 className="font-semibold text-base">{item.title}</h4>
                  <p className="text-sm text-[var(--foreground-muted)] mt-0.5 leading-6">{item.desc}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}

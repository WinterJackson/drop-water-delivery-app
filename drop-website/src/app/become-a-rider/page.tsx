import { Button } from "@/components/ui/Button";
import Link from "next/link";
import { Clock, MapPin, Wallet, Zap } from "lucide-react";

const benefits = [
  {
    title: "Be Your Own Boss",
    description: "Work when you want, where you want. Turn on the app to start receiving delivery requests instantly.",
    icon: Clock,
  },
  {
    title: "Instant Payouts",
    description: "Your earnings go straight into your Drop Digital Wallet. Withdraw to M-Pesa anytime, 24/7.",
    icon: Wallet,
  },
  {
    title: "Optimized Routes",
    description: "Our in-app navigation finds the fastest route from the vendor to the customer\u2019s doorstep.",
    icon: MapPin,
  },
  {
    title: "Consistent Demand",
    description: "Water is an essential need. Enjoy a steady stream of delivery requests throughout the day.",
    icon: Zap,
  },
];

const requirements = [
  "Valid National ID",
  "A reliable motorcycle or bicycle",
  "Valid Rider\u2019s License (for motorcycles)",
  "An Android smartphone with GPS capabilities",
  "Certificate of Good Conduct",
];

export default function BecomeRiderPage() {
  return (
    <div className="bg-[var(--background)]">
      {/* Hero Section */}
      <section className="py-16 sm:py-24 bg-[var(--chrome)] text-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent" />
        <div className="relative mx-auto max-w-[1100px] px-6 lg:px-8">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl lg:text-5xl mb-5">
            Drive with Drop. Earn on your schedule.
          </h1>
          <p className="text-base text-white/85 sm:text-lg max-w-xl mx-auto mb-8 leading-relaxed">
            Turn your motorcycle or bicycle into a money-making machine. Deliver clean water to households in your area.
          </p>
          <Link href="/contact">
            <Button size="lg" className="bg-white text-[var(--accent)] font-bold px-8 shadow-lg hover:bg-white/90 hover:shadow-xl">
              Sign Up to Ride
            </Button>
          </Link>
        </div>
      </section>

      {/* Benefits */}
      <section className="py-20 sm:py-28">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <h2 className="text-2xl font-bold text-center mb-12">Why ride with Drop?</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {benefits.map((benefit) => (
              <div key={benefit.title} className="flex flex-col items-center text-center p-6 rounded-2xl bg-[var(--surface)] border border-[var(--border)] shadow-sm transition-all hover:-translate-y-1 hover:shadow-md">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--accent-subtle)] mb-4">
                  <benefit.icon className="h-6 w-6 text-[var(--accent)]" />
                </div>
                <h3 className="text-base font-bold mb-2">{benefit.title}</h3>
                <p className="text-sm leading-6 text-[var(--foreground-muted)]">{benefit.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Requirements */}
      <section className="py-20 sm:py-28 bg-[var(--surface-muted)]">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <div className="bg-[var(--surface)] p-8 sm:p-10 rounded-2xl border border-[var(--border)] shadow-sm">
            <h2 className="text-2xl font-bold mb-7 text-center">Rider Requirements</h2>
            <ul className="space-y-3.5">
              {requirements.map((req) => (
                <li key={req} className="flex items-center gap-3 text-sm text-[var(--foreground-muted)]">
                  <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />
                  {req}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

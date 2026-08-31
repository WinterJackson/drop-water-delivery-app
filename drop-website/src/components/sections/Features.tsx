import { User, Store, Bike } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";

const personas = [
  {
    title: "For Customers",
    icon: User,
    features: [
      "Browse trusted local vendors",
      "Order water with two taps",
      "Real-time live map tracking",
      "Secure M-Pesa payments",
      "Rate your delivery experience",
    ],
    cta: "Get the App",
    href: "/apps",
  },
  {
    title: "For Vendors",
    icon: Store,
    features: [
      "Manage your digital storefront",
      "Accept and dispatch orders",
      "Track your riders live",
      "Built-in digital wallet",
      "Advanced sales analytics",
    ],
    cta: "Become a Vendor",
    href: "/become-a-vendor",
  },
  {
    title: "For Riders",
    icon: Bike,
    features: [
      "Accept delivery requests",
      "Turn-by-turn navigation",
      "Earn on your own schedule",
      "Instant payout to wallet",
      "Flexible working hours",
    ],
    cta: "Drive with Drop",
    href: "/become-a-rider",
  },
];

export function Features() {
  return (
    <section className="py-20 sm:py-28 bg-[var(--surface-muted)]">
      <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center mb-14">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">The Complete Platform</h2>
          <p className="mt-4 text-base leading-7 text-[var(--foreground-muted)] sm:text-lg">
            A unified ecosystem connecting everyone in the water delivery chain.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-3 lg:gap-8">
          {personas.map((persona) => (
            <div key={persona.title} className="flex flex-col rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-7 shadow-sm transition-shadow hover:shadow-md">
              <div className="flex items-center gap-3.5 mb-5">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                  <persona.icon className="h-5 w-5 text-[var(--accent)]" />
                </div>
                <h3 className="text-xl font-bold">{persona.title}</h3>
              </div>
              
              <ul className="flex-1 space-y-3 mb-7">
                {persona.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2.5">
                    <div className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />
                    <span className="text-sm leading-6 text-[var(--foreground-muted)]">{feature}</span>
                  </li>
                ))}
              </ul>
              
              <Link href={persona.href}>
                <Button variant="outline" className="w-full">{persona.cta}</Button>
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

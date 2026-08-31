import { Search, Map, Droplet } from "lucide-react";

const steps = [
  {
    title: "Browse & Order",
    description: "Find nearby water vendors, compare prices, and order with a tap on your phone.",
    icon: Search,
  },
  {
    title: "Track in Real-Time",
    description: "Watch your rider on a live map from pickup to your doorstep. No more guessing.",
    icon: Map,
  },
  {
    title: "Stay Hydrated",
    description: "Get clean water delivered quickly. Pay securely via M-Pesa once it arrives.",
    icon: Droplet,
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-20 sm:py-28 bg-[var(--background)]">
      <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">How It Works</h2>
          <p className="mt-4 text-base leading-7 text-[var(--foreground-muted)] sm:text-lg">
            Getting clean water has never been easier. Three simple steps and you&apos;re done.
          </p>
        </div>
        
        <div className="mx-auto mt-14 max-w-5xl sm:mt-18 lg:max-w-none">
          <div className="grid max-w-xl grid-cols-1 gap-6 lg:max-w-none lg:grid-cols-3 lg:gap-8">
            {steps.map((step, index) => (
              <div
                key={step.title}
                className="flex flex-col items-center text-center rounded-2xl bg-[var(--surface)] border border-[var(--border)] p-8 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-md"
              >
                <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-xl bg-[var(--accent-subtle)]">
                  <step.icon className="h-7 w-7 text-[var(--accent)]" aria-hidden="true" />
                </div>
                <h3 className="text-lg font-semibold leading-7">
                  <span className="text-[var(--accent)] mr-1.5">{index + 1}.</span>
                  {step.title}
                </h3>
                <p className="mt-3 text-sm leading-6 text-[var(--foreground-muted)]">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

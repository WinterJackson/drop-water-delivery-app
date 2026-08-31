import { Hero } from "@/components/sections/Hero";
import { HowItWorks } from "@/components/sections/HowItWorks";
import { Features } from "@/components/sections/Features";
import Link from "next/link";
import { Button } from "@/components/ui/Button";

export default function Home() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <Features />

      {/* Pre-Launch CTA Banner */}
      <section className="py-20 sm:py-28 bg-[var(--background)]">
        <div className="mx-auto max-w-[1100px] px-6 lg:px-8">
          <div className="relative isolate overflow-hidden rounded-2xl bg-[var(--accent)] px-6 py-14 text-center shadow-xl sm:px-16 sm:py-18 flex flex-col items-center">
            <h2 className="mx-auto max-w-xl text-2xl font-bold tracking-tight text-white sm:text-3xl lg:text-4xl">
              We&apos;re building something special.
            </h2>
            <p className="mx-auto mt-4 max-w-lg text-sm leading-7 text-white/85 sm:text-base sm:leading-7">
              Drop is currently in beta testing. Be among the first to experience the future of water delivery in Kenya.
            </p>
            
            <div className="mt-7">
              <Link href="/apps">
                <Button size="lg" className="bg-white text-[var(--accent)] font-bold px-8 shadow-lg hover:bg-white/90 hover:shadow-xl">
                  Download the Beta
                </Button>
              </Link>
            </div>
            
            {/* Background radial */}
            <svg
              viewBox="0 0 1024 1024"
              className="absolute left-1/2 top-1/2 -z-10 h-[48rem] w-[48rem] -translate-x-1/2 -translate-y-1/2 [mask-image:radial-gradient(closest-side,white,transparent)]"
              aria-hidden="true"
            >
              <circle cx={512} cy={512} r={512} fill="url(#cta-gradient)" fillOpacity="0.5" />
              <defs>
                <radialGradient id="cta-gradient">
                  <stop stopColor="white" />
                  <stop offset={1} stopColor="white" stopOpacity="0" />
                </radialGradient>
              </defs>
            </svg>
          </div>
        </div>
      </section>
    </>
  );
}

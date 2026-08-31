import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/Button";

export function Hero() {
  return (
    <section className="relative overflow-hidden bg-[var(--chrome)] pt-16 pb-24 text-[var(--chrome-foreground)] sm:pt-20 sm:pb-32 lg:pt-28 lg:pb-40">
      {/* Layered gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-transparent via-transparent to-black/20" />
      
      <div className="relative mx-auto max-w-[1100px] px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:items-center lg:gap-16">
          
          {/* Copy */}
          <div className="flex flex-col items-center text-center lg:items-start lg:text-left">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/25 bg-white/10 px-4 py-1.5 text-sm font-medium backdrop-blur-sm">
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-bold text-[var(--accent)]">BETA</span>
              🚀 Coming Soon — Currently in Beta Testing
            </div>
            
            <h1 className="mb-5 text-4xl font-bold leading-[1.1] text-white sm:text-5xl lg:text-6xl">
              Clean Water, <br className="hidden sm:block" /> Delivered to Your Door
            </h1>
            
            <p className="mb-8 max-w-lg text-base leading-relaxed text-white/85 sm:text-lg sm:leading-relaxed">
              Kenya&apos;s multivendor water delivery marketplace. Order from local vendors, track your rider in real-time, and never run dry.
            </p>
            
            <div className="flex flex-col gap-3 sm:flex-row w-full sm:w-auto">
              <Link href="/apps" className="w-full sm:w-auto">
                <Button size="lg" className="w-full bg-white text-[var(--accent)] font-bold shadow-lg shadow-black/15 hover:bg-white/90 hover:shadow-xl">
                  Try the Beta
                </Button>
              </Link>
              <Link href="#how-it-works" className="w-full sm:w-auto">
                <Button size="lg" variant="outline" className="w-full border-white/30 bg-white/10 text-white hover:bg-white/20 backdrop-blur-sm">
                  Learn More
                </Button>
              </Link>
            </div>
          </div>
          
          {/* Mascot */}
          <div className="relative mx-auto flex w-full max-w-sm justify-center lg:max-w-md lg:justify-end">
            <div className="relative z-10 animate-fade-in-up">
              <Image 
                src="/dropy/dropy_hero.webp"
                alt="Dropy the water droplet mascot"
                width={360}
                height={360}
                priority
                className="drop-shadow-2xl transition-transform duration-500 hover:scale-[1.03]"
              />
            </div>
            {/* Glow behind mascot */}
            <div className="absolute top-1/2 left-1/2 -z-0 h-56 w-56 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/15 blur-3xl lg:h-80 lg:w-80" />
          </div>

        </div>
      </div>
    </section>
  );
}

import { Metadata } from "next";
import { PitchDeckView } from "./PitchDeckView";

export const metadata: Metadata = {
  title: "Investor Pitch Deck | Drop — Water Delivery Platform",
  description: "Official pitch deck and investor presentation for Drop, Kenya's premier multivendor water delivery platform.",
};

export default function PitchDeckPage() {
  return <PitchDeckView />;
}

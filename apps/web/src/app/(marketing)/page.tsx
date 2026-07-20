import type { Metadata } from "next";

export const dynamic = "force-dynamic";

import { HeroSection } from "@/components/marketing/HeroSection";
import { TrustStrip } from "@/components/marketing/TrustStrip";
import { FeatureGrid } from "@/components/marketing/FeatureGrid";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { PricingTeaser } from "@/components/marketing/PricingTeaser";
import { TestimonialsCarousel } from "@/components/marketing/TestimonialsCarousel";
import { FAQAccordion } from "@/components/marketing/FAQAccordion";
import { CTABanner } from "@/components/marketing/CTABanner";

const TITLE = "Credyx — B2B Credit Intelligence";
const DESCRIPTION =
  "Search 112 country registries, pull filed financials, score credit risk in seconds. Live, deterministic, audit-ready.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    images: ["/og/og-home.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/og/og-home.png"],
  },
};

export default function MarketingHome() {
  return (
    <>
      <HeroSection />
      <TrustStrip />
      <FeatureGrid />
      <HowItWorks />
      <PricingTeaser />
      <TestimonialsCarousel />
      <FAQAccordion />
      <CTABanner />
    </>
  );
}

import type { Metadata } from "next";
import { Arimo, Geist_Mono, Open_Sans } from "next/font/google";
import { connection } from "next/server";
import { Analytics } from "@vercel/analytics/next";

import { readAuthRuntimeConfig } from "@/lib/auth-config";

import Providers from "./providers";
import "@xyflow/react/dist/style.css";
import "./globals.css";

const arimo = Arimo({
  variable: "--font-arimo",
  subsets: ["latin"],
  display: "swap",
});

const openSans = Open_Sans({
  variable: "--font-open-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Tributary",
  description:
    "A local-first feed reader with a stream you control. No account, no algorithm.",
};

// Auth0 settings are read per request, so every route is rendered at request
// time. Opt out of the static-shell check instead of caching cloud config.
export const instant = false;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Read the profile per request so a hosted deployment can change Auth0
  // settings without rebuilding the browser bundle.
  await connection();
  const auth = readAuthRuntimeConfig(process.env);

  return (
    <html
      lang="en"
      className={`${arimo.variable} ${openSans.variable} ${geistMono.variable}`}
    >
      <body>
        <Providers auth={auth}>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );
}

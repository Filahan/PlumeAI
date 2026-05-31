import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { StoreProvider } from "@/lib/store-provider";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "WebUI - Chat Interface",
  description: "Simple, clean chat interface for LLMs",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} antialiased font-sans`}>
        <StoreProvider>
          <TooltipProvider delay={300}>{children}</TooltipProvider>
        </StoreProvider>
      </body>
    </html>
  );
}

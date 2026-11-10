import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dockflow — Inbound operations simulator",
  description: "A fictional inbound operations console. Explore trailer priority, destination demand, and operator-approved door assignments using synthetic data.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Code Autopsy Viewer",
  description: "Interactive X-Ray onboarding dashboard"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

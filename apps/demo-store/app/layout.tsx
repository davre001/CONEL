import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {
  title: "CONEL Demo Store",
  description: "A controlled checkout recovery demonstration",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

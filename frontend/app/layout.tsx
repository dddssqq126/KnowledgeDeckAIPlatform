import type { Metadata } from "next";
import "./globals.css";
import { UserProvider } from "./UserContext";

export const metadata: Metadata = {
  title: "KnowledgeDeck",
  description: "AI chat, RAG, and editable PPTX generation platform",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <UserProvider>{children}</UserProvider>
      </body>
    </html>
  );
}

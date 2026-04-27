import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KnowledgeDeck",
  description: "AI chat, RAG, and editable PPTX generation platform"
};

const themeInitScript = `
(() => {
  try {
    const mode = localStorage.getItem('knowledgedeck-theme');
    if (mode === 'dark') {
      document.documentElement.classList.add('dark');
    }
  } catch {}
})();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}

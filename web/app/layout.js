import "./globals.css";

export const metadata = {
  title: "Lauds",
  description: "Lauds: the first thing you check in the morning.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

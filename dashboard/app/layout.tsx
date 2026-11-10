import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title:'Echo · Research workspace', description:'Design thoughtful research. Listen on WhatsApp. Review every decision.' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>}

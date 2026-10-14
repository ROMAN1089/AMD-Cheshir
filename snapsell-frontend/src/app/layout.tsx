import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'SnapSell — A second life. A smarter sale.',description:'Turn your inventory into opportunity. Video-to-catalog and explainable resale decisions, powered by AMD.'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}

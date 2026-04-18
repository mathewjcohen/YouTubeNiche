import type { Metadata } from 'next'
import './globals.css'
import { Nav } from '@/components/nav'
import { AutoRefresh } from '@/components/auto-refresh'

export const metadata: Metadata = { title: 'YouTubeNiche Dashboard' }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen bg-gray-900 text-gray-100">
        <Nav />
        <main className="flex-1 p-6 overflow-auto">{children}</main>
        <AutoRefresh />
      </body>
    </html>
  )
}

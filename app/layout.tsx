import type { Metadata } from 'next';
import './globals.css';

const siteOrigin = process.env.NEXT_PUBLIC_SITE_ORIGIN ?? 'http://localhost:3000';
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
const socialImage = new URL(`${basePath}/og.png`, siteOrigin).toString();

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin),
  title: '嵌入式面试知识库',
  description: '持续整理 C/C++、STM32、RTOS、操作系统、计算机网络与 Linux 驱动面试知识点。',
  openGraph: {
    title: '嵌入式面试知识库',
    description: '把零散面经，整理成可检索的嵌入式知识体系。',
    type: 'website',
    images: [{ url: socialImage, width: 1731, height: 909, alt: '嵌入式面试知识库' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '嵌入式面试知识库',
    description: '把零散面经，整理成可检索的嵌入式知识体系。',
    images: [socialImage],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

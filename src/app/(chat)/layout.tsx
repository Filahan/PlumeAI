import { ReactNode } from 'react';
import ChatLayout from '@/components/chat-layout';

export default function ChatGroupLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <ChatLayout />
      {children}
    </>
  );
}

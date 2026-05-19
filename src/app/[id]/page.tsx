'use client';

import { useParams } from 'next/navigation';
import ChatLayout from '@/components/chat-layout';

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  return <ChatLayout currentId={params.id ?? null} />;
}

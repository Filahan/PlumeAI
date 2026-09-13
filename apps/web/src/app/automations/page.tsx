import { redirect } from 'next/navigation';

/** `/automations` has no list page of its own — the list is the left panel on `/`. */
export default function AutomationsIndexPage() {
  redirect('/');
}

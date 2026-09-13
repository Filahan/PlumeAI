import { redirect } from 'next/navigation';

/** Usage became the Spend tab of Activity. Old links (and anyone's bookmark) keep
 *  working — they land on the same page under its new address. */
export default function UsagePage() {
  redirect('/activity/spend');
}

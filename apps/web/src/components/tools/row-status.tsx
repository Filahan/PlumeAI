/** The Status cell. `ok` gets the dot, everything else is a plain phrase — the reason a
 *  row isn't usable (the server's last error) rides along in `title`. */
export default function RowStatus({
  tone,
  label,
  title,
}: {
  tone: 'ok' | 'muted' | 'danger';
  label: string;
  title?: string;
}) {
  if (tone === 'ok') {
    return (
      <span className="flex items-center gap-1.5 text-[12px] font-medium text-[#10A37F]">
        <span className="w-1.5 h-1.5 rounded-full bg-[#10A37F]" aria-hidden="true" />
        {label}
      </span>
    );
  }
  return (
    <span
      title={title}
      className={`block truncate text-[12px] font-medium ${
        tone === 'danger' ? 'text-[#D4183D]' : 'text-[color:var(--muted-foreground)]'
      }`}
    >
      {label}
    </span>
  );
}

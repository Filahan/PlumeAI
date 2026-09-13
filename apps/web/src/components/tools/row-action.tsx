/** The right-hand control of a row: quiet text for a tool you already have, an outline
 *  pill for the one call to action ("Connect"). Both open the same dialog the row does. */
export default function RowAction({
  variant,
  label,
  ariaLabel,
  onClick,
}: {
  variant: 'quiet' | 'outline';
  label: string;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={
        variant === 'quiet'
          ? 'h-[30px] px-2 inline-flex items-center rounded-[10px] text-[12px] font-medium text-[color:var(--muted-foreground)] transition hover:text-[color:var(--foreground)]'
          : 'h-[30px] px-3 inline-flex items-center rounded-[10px] border border-[color:var(--border)] bg-white text-[12px] font-medium transition hover:bg-[color:var(--surface-muted)]'
      }
    >
      {label}
    </button>
  );
}

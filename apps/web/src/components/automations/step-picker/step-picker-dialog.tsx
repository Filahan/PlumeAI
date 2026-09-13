'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useAutomationsStore, useCatalog } from '@/lib/automations/store';
import type { AutomationStep, CatalogAction, CatalogIntegration } from '@/lib/automations/types';
import NodeIcon from '@/components/automations/canvas/node-icon';
import StepPickerItem from '@/components/automations/step-picker/step-picker-item';
import {
  newActionStep,
  newAiStep,
  newFilterStep,
} from '@/components/automations/step-picker/new-step';

/** Every search term has to appear somewhere in the row's text. */
function matches(query: string, ...fields: (string | undefined)[]): boolean {
  if (!query) return true;
  const haystack = fields.filter(Boolean).join(' ').toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

function actionsFor(integration: CatalogIntegration, query: string): CatalogAction[] {
  // A matching integration name shows the whole integration; otherwise match per action.
  if (matches(query, integration.name, integration.label)) return integration.actions;
  return integration.actions.filter((a) => matches(query, a.label, a.name, a.description));
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pt-3 pb-1 text-[10px] font-medium uppercase tracking-[0.08em] text-[color:var(--muted-foreground)]">
      {children}
    </p>
  );
}

/** "What should happen next?" — the one place new steps are born.
 *
 *  Driven by the store's `stepPicker` slice: `index` is the position the new step takes
 *  in `document.steps`, so the same dialog serves the "+" on every edge, the trailing
 *  card and the empty state. Choosing a row writes one operation and selects the new
 *  step, which opens the inspector on it. */
export default function StepPickerDialog({
  open,
  index,
  onOpenChange,
}: {
  open: boolean;
  index: number | null;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const catalog = useCatalog();
  const applyOperations = useAutomationsStore((s) => s.applyOperations);
  const select = useAutomationsStore((s) => s.select);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);

  /** Closing is the only way out, so resetting the search here is enough to guarantee
   *  the dialog always opens empty — no effect needed. */
  const setOpen = (next: boolean) => {
    if (!next) setQuery('');
    onOpenChange(next);
  };

  const insert = async (step: AutomationStep) => {
    if (busy || index === null) return;
    setBusy(true);
    try {
      await applyOperations([{ op: 'add_step', step, index }]);
      select({ kind: 'step', stepId: step.id });
      setOpen(false);
    } catch {
      // `applyOperations` already put the reason in `current.saveError`, which the
      // editor shell shows as a banner. Leave the dialog open so nothing is lost.
    } finally {
      setBusy(false);
    }
  };

  /** Connected integrations first: those are the only ones that can be picked. */
  const integrations = useMemo(() => {
    const rows = (catalog?.integrations ?? []).map((integration) => ({
      integration,
      actions: actionsFor(integration, query),
    }));
    return rows
      .filter((row) => row.actions.length > 0)
      .sort((a, b) => Number(b.integration.connected) - Number(a.integration.connected));
  }, [catalog, query]);

  const builtins = useMemo(
    () =>
      (catalog?.builtinActions ?? []).filter((a) =>
        matches(query, a.label, a.name, a.description, 'built-in')
      ),
    [catalog, query]
  );

  const showAi = matches(query, 'AI step', 'model', 'write', 'summarize', 'reason');
  const showFilter = matches(query, 'Filter', 'condition', 'stop', 'only if');
  const empty = !showAi && !showFilter && integrations.length === 0 && builtins.length === 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-lg gap-0 p-0 overflow-hidden">
        <DialogHeader className="px-4 pt-4 pb-3 pr-10 gap-1">
          <DialogTitle>Add a step</DialogTitle>
          <DialogDescription>
            {index === null || index === 0
              ? 'It runs first, right after the trigger.'
              : `It runs as step ${index + 1}.`}
          </DialogDescription>
          <div className="relative mt-2">
            <Search
              size={13}
              strokeWidth={2}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--muted-foreground)]"
            />
            <Input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search apps and actions…"
              aria-label="Search steps"
              className="h-9 pl-8 text-[13px]"
            />
          </div>
        </DialogHeader>

        <div className="max-h-[52vh] overflow-y-auto border-t border-[color:var(--border)] px-2 pb-3">
          {showAi && (
            <>
              <SectionLabel>AI step</SectionLabel>
              <StepPickerItem
                icon={<NodeIcon kind="ai" />}
                title="AI step"
                description="Let the model read earlier steps and write the result."
                onSelect={() => void insert(newAiStep())}
              />
            </>
          )}

          {showFilter && (
            <>
              <SectionLabel>Filter</SectionLabel>
              <StepPickerItem
                icon={<NodeIcon kind="filter" />}
                title="Filter"
                description="Stop the run here unless a condition holds."
                onSelect={() => void insert(newFilterStep())}
              />
            </>
          )}

          {integrations.map(({ integration, actions }) => (
            <div key={integration.name}>
              <SectionLabel>
                {integration.label}
                {!integration.connected && ' · not connected'}
              </SectionLabel>
              {actions.map((action) => (
                <StepPickerItem
                  key={action.name}
                  icon={<NodeIcon kind="action" integration={action.integration} />}
                  title={action.label}
                  description={action.description}
                  disabled={!integration.connected}
                  onSelect={() => void insert(newActionStep(action))}
                  onConnect={() => router.push('/tools')}
                />
              ))}
            </div>
          ))}

          {builtins.length > 0 && (
            <>
              <SectionLabel>Built-in</SectionLabel>
              {builtins.map((action) => (
                <StepPickerItem
                  key={action.name}
                  icon={<NodeIcon kind="action" integration={action.integration} />}
                  title={action.label}
                  description={action.description}
                  onSelect={() => void insert(newActionStep(action))}
                />
              ))}
            </>
          )}

          {empty && (
            <p className="px-2.5 py-6 text-center text-[12px] text-[color:var(--muted-foreground)]">
              Nothing matches “{query}”.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

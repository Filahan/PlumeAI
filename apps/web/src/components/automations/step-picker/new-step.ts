/** Builders for the step the picker inserts.
 *
 *  Every builder is deliberately minimal: a fresh id, a name the user will recognise,
 *  and the emptiest settings the document language accepts. Required action inputs are
 *  left unset on purpose — the server comes straight back with `valid: false` plus the
 *  issues that say what is missing, and the inspector fills them in. That is cheaper
 *  than guessing, and it makes "what still needs doing" visible on the canvas from the
 *  moment a step exists.
 *
 *  `valid: true` here is a placeholder the backend always recomputes.
 */

import {
  newStepId,
  type ActionStep,
  type AiStep,
  type CatalogAction,
  type FilterStep,
} from '@/lib/automations/types';

export function newActionStep(action: CatalogAction): ActionStep {
  return {
    id: newStepId(),
    name: action.label || action.name,
    type: 'action',
    valid: true,
    settings: { integration: action.integration, action: action.name, input: {} },
  };
}

const AI_STEP_PLACEHOLDER = 'Summarise what the previous step returned.';

/** The instruction is seeded rather than left empty: the document schema demands at
 *  least one character (`min_length=1`), so an empty string never reaches the canvas —
 *  `POST /operations` answers 422 and the step is simply never created. A placeholder
 *  the user overwrites in the inspector is the honest default. */
export function newAiStep(): AiStep {
  return {
    id: newStepId(),
    name: 'AI step',
    type: 'ai',
    valid: true,
    settings: {
      instructions: AI_STEP_PLACEHOLDER,
      tools: [],
      output: { mode: 'text' },
    },
  };
}

/** Seeded with a condition that is always true (`trigger.date` is filled on every run),
 *  so a brand-new filter is a valid document the user can then narrow down. */
export function newFilterStep(): FilterStep {
  return {
    id: newStepId(),
    name: 'Filter',
    type: 'filter',
    valid: true,
    settings: {
      mode: 'rules',
      rules: {
        combinator: 'and',
        conditions: [{ left: { kind: 'ref', value: '{{trigger.date}}' }, op: 'is_not_empty' }],
      },
    },
  };
}

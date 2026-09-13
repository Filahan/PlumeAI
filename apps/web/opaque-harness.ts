import { readFileSync } from 'fs';
import { isOpaqueIdentifier } from './src/components/automations/inspector/schema-form/opaque-field';

type Field = { integration: string; action: string; name: string; schema: Record<string, unknown> };

const catalog = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const fields: Field[] = [];
const push = (integration: string, actions: any[]) => {
  for (const a of actions ?? []) {
    const props = (a.inputSchema ?? {}).properties ?? {};
    for (const [name, schema] of Object.entries(props)) {
      fields.push({ integration, action: a.name, name, schema: schema as Record<string, unknown> });
    }
  }
};
for (const i of catalog.integrations ?? []) push(i.name, i.actions);
push('builtin', catalog.builtinActions ?? []);
for (const s of catalog.mcpServers ?? []) push(`mcp:${s.name}`, s.actions);

const flagged = fields.filter((f) => isOpaqueIdentifier(f.name, f.schema));
const plain = fields.filter((f) => !isOpaqueIdentifier(f.name, f.schema));
const show = (f: Field) =>
  `${f.integration}.${f.action}.${f.name} [${String((f.schema as any).type)}]`;
console.log(`=== FLAGGED (${flagged.length}) ===`);
for (const f of flagged) console.log('  ' + show(f));
console.log(`=== NOT FLAGGED (${plain.length}) ===`);
for (const f of plain) console.log('  ' + show(f));

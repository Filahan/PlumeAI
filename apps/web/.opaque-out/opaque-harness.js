"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const fs_1 = require("fs");
const opaque_field_1 = require("./src/components/automations/inspector/schema-form/opaque-field");
const catalog = JSON.parse((0, fs_1.readFileSync)(process.argv[2], 'utf8'));
const fields = [];
const push = (integration, actions) => {
    for (const a of actions ?? []) {
        const props = (a.inputSchema ?? {}).properties ?? {};
        for (const [name, schema] of Object.entries(props)) {
            fields.push({ integration, action: a.name, name, schema: schema });
        }
    }
};
for (const i of catalog.integrations ?? [])
    push(i.name, i.actions);
push('builtin', catalog.builtinActions ?? []);
for (const s of catalog.mcpServers ?? [])
    push(`mcp:${s.name}`, s.actions);
const flagged = fields.filter((f) => (0, opaque_field_1.isOpaqueIdentifier)(f.name, f.schema));
const plain = fields.filter((f) => !(0, opaque_field_1.isOpaqueIdentifier)(f.name, f.schema));
const show = (f) => `${f.integration}.${f.action}.${f.name} [${String(f.schema.type)}]`;
console.log(`=== FLAGGED (${flagged.length}) ===`);
for (const f of flagged)
    console.log('  ' + show(f));
console.log(`=== NOT FLAGGED (${plain.length}) ===`);
for (const f of plain)
    console.log('  ' + show(f));

import 'server-only';
import postgres from 'postgres';
import { drizzle } from 'drizzle-orm/postgres-js';
import { migrate } from 'drizzle-orm/postgres-js/migrator';

const url = process.env.DATABASE_URL;
if (!url) {
  throw new Error('DATABASE_URL is required');
}

// In dev with HMR, reuse the connection across reloads.
declare global {
  var __plumeai_postgres__: ReturnType<typeof postgres> | undefined;
}

const client =
  process.env.NODE_ENV === 'production'
    ? postgres(url, { max: 5 })
    : (global.__plumeai_postgres__ ?? (global.__plumeai_postgres__ = postgres(url, { max: 5 })));

export const db = drizzle(client);

let migrationPromise: Promise<void> | null = null;
export function ensureMigrations(): Promise<void> {
  if (migrationPromise) return migrationPromise;
  migrationPromise = migrate(db, { migrationsFolder: './drizzle' }).catch((err) => {
    migrationPromise = null;
    throw err;
  });
  return migrationPromise;
}

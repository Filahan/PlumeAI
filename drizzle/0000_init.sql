CREATE TABLE "conversations" (
	"id" text PRIMARY KEY NOT NULL,
	"title" text NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "messages" (
	"id" text PRIMARY KEY NOT NULL,
	"conversation_id" text NOT NULL,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"attachments" jsonb,
	"timestamp" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "settings" (
	"id" integer PRIMARY KEY DEFAULT 1 NOT NULL,
	"providers" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"default_model" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tasks" (
	"id" text PRIMARY KEY NOT NULL,
	"owner_id" text,
	"prompt" text NOT NULL,
	"messages" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"schedule" text DEFAULT 'manual' NOT NULL,
	"status" text DEFAULT 'idle' NOT NULL,
	"output" text,
	"transcript" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "usage_entries" (
	"id" text PRIMARY KEY NOT NULL,
	"conversation_id" text,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"input_tokens" integer NOT NULL,
	"output_tokens" integer NOT NULL,
	"timestamp" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_conversation_id_conversations_id_fk" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "messages_conversation_idx" ON "messages" USING btree ("conversation_id");--> statement-breakpoint
CREATE INDEX "messages_timestamp_idx" ON "messages" USING btree ("timestamp");--> statement-breakpoint
CREATE INDEX "tasks_created_idx" ON "tasks" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "usage_timestamp_idx" ON "usage_entries" USING btree ("timestamp");--> statement-breakpoint
CREATE INDEX "usage_provider_idx" ON "usage_entries" USING btree ("provider");
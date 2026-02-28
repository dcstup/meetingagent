import dotenv from "dotenv";
import { z } from "zod";

dotenv.config({ path: "../../.env" });
dotenv.config();

const envSchema = z.object({
  PORT: z.coerce.number().default(8080),
  OPENAI_API_KEY: z.string().optional(),
  OPENAI_MODEL: z.string().default("gpt-4.1-mini"),
  DEEPGRAM_API_KEY: z.string().optional(),
  COMPOSIO_API_KEY: z.string().optional(),
  COMPOSIO_BASE_URL: z.string().url().optional(),
  COMPOSIO_EXEC_MODE: z.enum(["mock", "http", "python_agents"]).default("mock"),
  COMPOSIO_EXTERNAL_USER_ID: z.string().optional(),
  COMPOSIO_PYTHON_BIN: z.string().default("python3"),
  SUPABASE_URL: z.string().url().optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().optional()
});

export const env = envSchema.parse(process.env);

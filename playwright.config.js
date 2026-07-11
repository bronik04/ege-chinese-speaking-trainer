import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const dataDir = process.env.E2E_DATA_DIR || path.join(os.tmpdir(), `ege-trainer-e2e-${process.pid}`);
const python = process.env.E2E_PYTHON || ".venv/bin/python";
process.env.E2E_DATA_DIR = dataDir;

export default defineConfig({
  testDir: "./tests-e2e",
  timeout: 45_000,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:8091", trace: "retain-on-failure" },
  webServer: {
    command: `${python} -m uvicorn asgi:app --host 127.0.0.1 --port 8091`,
    url: "http://127.0.0.1:8091/api/health",
    reuseExistingServer: false,
    env: {
      ...process.env,
      TRAINER_DATA_DIR: dataDir,
      TRAINER_TRANSCRIPTION_ENABLED: "0",
      TRAINER_TEACHER_EMAILS: "workflow-teacher@example.test,resend-teacher@example.test,unverified-teacher@example.test,snapshot-teacher@example.test",
      TRAINER_EDITOR_MODE: "allowlist",
      TRAINER_EDITOR_EMAILS: "catalog-author@example.test",
    },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});

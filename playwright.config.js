import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const dataDir = path.join(os.tmpdir(), `ege-trainer-e2e-${process.pid}`);

export default defineConfig({
  testDir: "./tests-e2e",
  timeout: 45_000,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:8091", trace: "retain-on-failure" },
  webServer: {
    command: ".venv/bin/uvicorn asgi:app --host 127.0.0.1 --port 8091",
    url: "http://127.0.0.1:8091/api/health",
    reuseExistingServer: false,
    env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_TRANSCRIPTION_ENABLED: "0" },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});

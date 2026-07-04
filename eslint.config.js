export default [{
  files: ["app.js", "js/**/*.js", "tests-js/**/*.js"],
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    globals: {
      AudioContext: "readonly",
      Blob: "readonly",
      FormData: "readonly",
      Intl: "readonly",
      Map: "readonly",
      MediaRecorder: "readonly",
      URL: "readonly",
      URLSearchParams: "readonly",
      clearInterval: "readonly",
      clearTimeout: "readonly",
      confirm: "readonly",
      console: "readonly",
      crypto: "readonly",
      document: "readonly",
      fetch: "readonly",
      localStorage: "readonly",
      navigator: "readonly",
      prompt: "readonly",
      setInterval: "readonly",
      setTimeout: "readonly",
      window: "readonly"
    }
  },
  rules: {
    "no-undef": "error",
    "no-unused-vars": ["error", { "argsIgnorePattern": "^_", "caughtErrors": "none" }]
  }
}];

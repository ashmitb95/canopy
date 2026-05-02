import type { Config } from "jest";

const config: Config = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/*.test.ts"],
  // Mock the `vscode` module across all tests — extension code can `import
  // * as vscode from "vscode"` and tests get the stub from src/__mocks__/vscode.ts.
  moduleNameMapper: {
    "^vscode$": "<rootDir>/src/__mocks__/vscode.ts",
  },
  // Quiet output by default; pass --verbose for the per-test view.
  reporters: ["jest-silent-reporter"],
  // ts-jest is fast enough to skip incremental builds — keeps test runs
  // deterministic.
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { isolatedModules: true }],
  },
};

export default config;

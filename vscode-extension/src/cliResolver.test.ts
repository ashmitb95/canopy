import * as fs from "node:fs";
import * as path from "node:path";

import { resolveCanopyCli } from "./cliResolver";

jest.mock("node:fs");
jest.mock("node:child_process", () => ({
  execFileSync: jest.fn(),
}));

const mockedFs = fs as jest.Mocked<typeof fs>;
const { execFileSync } = jest.requireMock("node:child_process") as {
  execFileSync: jest.Mock;
};

beforeEach(() => {
  jest.clearAllMocks();
  mockedFs.existsSync.mockReturnValue(false);
  execFileSync.mockReset();
});

describe("resolveCanopyCli — settings path (absolute)", () => {
  it("returns the configured path when it exists", () => {
    mockedFs.existsSync.mockImplementation(
      (p: fs.PathLike) => String(p) === "/opt/canopy/bin/canopy",
    );
    const out = resolveCanopyCli("/opt/canopy/bin/canopy", null);
    expect(out.resolvedVia).toBe("settings");
    expect(out.path).toBe("/opt/canopy/bin/canopy");
    expect(out.tried).toContain("/opt/canopy/bin/canopy");
  });

  it("falls through when the configured absolute path is missing", () => {
    // mockedFs.existsSync default returns false → settings doesn't match.
    // Login shell also fails (configured path has a slash, so we skip it),
    // disk scan also returns false → unresolved.
    const out = resolveCanopyCli("/nonexistent/canopy", null);
    expect(out.resolvedVia).toBe("unresolved");
    expect(out.path).toBe("/nonexistent/canopy");
  });
});

describe("resolveCanopyCli — login shell", () => {
  it("returns the path the login shell finds", () => {
    execFileSync.mockReturnValue("/Users/x/.local/bin/canopy\n");
    mockedFs.existsSync.mockImplementation(
      (p: fs.PathLike) => String(p) === "/Users/x/.local/bin/canopy",
    );
    const out = resolveCanopyCli("canopy", null);
    expect(out.resolvedVia).toBe("login-shell");
    expect(out.path).toBe("/Users/x/.local/bin/canopy");
  });

  it("ignores login-shell output when the returned path doesn't exist", () => {
    execFileSync.mockReturnValue("/ghost/path/canopy\n");
    // existsSync default → false; falls through to disk scan.
    const out = resolveCanopyCli("canopy", null);
    expect(out.resolvedVia).toBe("unresolved");
  });

  it("falls through silently if the login shell call throws", () => {
    execFileSync.mockImplementation(() => {
      throw new Error("shell missing");
    });
    const out = resolveCanopyCli("canopy", null);
    expect(out.resolvedVia).toBe("unresolved");
  });

  it("strips MOTD/init noise and uses the last printed path", () => {
    execFileSync.mockReturnValue([
      "Welcome to your shell",
      "Last login: …",
      "/Users/x/.local/bin/canopy",
      "",
    ].join("\n"));
    mockedFs.existsSync.mockImplementation(
      (p: fs.PathLike) => String(p) === "/Users/x/.local/bin/canopy",
    );
    const out = resolveCanopyCli("canopy", null);
    expect(out.path).toBe("/Users/x/.local/bin/canopy");
  });
});

describe("resolveCanopyCli — disk scan", () => {
  it("finds canopy in workspace .venv when present", () => {
    // Configured name "canopy"; login-shell stub returns nothing →
    // resolver moves on to disk scan with /ws/.venv/bin/canopy.
    const target = path.join("/ws", ".venv", "bin", "canopy");
    mockedFs.existsSync.mockImplementation((p: fs.PathLike) => String(p) === target);
    const out = resolveCanopyCli("canopy", "/ws");
    expect(out.resolvedVia).toBe("disk-scan");
    expect(out.path).toBe(target);
  });

  it("scans common per-user / system locations and returns the first match", () => {
    mockedFs.existsSync.mockImplementation(
      (p: fs.PathLike) => String(p) === "/opt/homebrew/bin/canopy",
    );
    const out = resolveCanopyCli("canopy", null);
    expect(out.resolvedVia).toBe("disk-scan");
    expect(out.path).toBe("/opt/homebrew/bin/canopy");
  });

  it("respects a custom binary name on disk scan", () => {
    // User configured a non-default name; disk scan uses that name in every
    // candidate path (vs hardcoding 'canopy').
    mockedFs.existsSync.mockImplementation(
      (p: fs.PathLike) => String(p) === "/opt/homebrew/bin/canopy-edge",
    );
    const out = resolveCanopyCli("canopy-edge", null);
    expect(out.resolvedVia).toBe("disk-scan");
    expect(out.path).toBe("/opt/homebrew/bin/canopy-edge");
  });

  it("records every path tried so callers can surface 'where we looked'", () => {
    const out = resolveCanopyCli("canopy", null);
    expect(out.resolvedVia).toBe("unresolved");
    // All disk-scan candidates appear in `tried`.
    expect(out.tried.some((p) => p.endsWith("/.local/bin/canopy"))).toBe(true);
    expect(out.tried.some((p) => p.endsWith("/opt/homebrew/bin/canopy"))).toBe(true);
  });
});

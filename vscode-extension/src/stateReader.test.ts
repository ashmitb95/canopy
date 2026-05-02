import * as fs from "node:fs";

import { StateReader, parseCanopyTomlMinimal } from "./stateReader";

jest.mock("node:fs");
const mockedFs = fs as jest.Mocked<typeof fs>;

beforeEach(() => {
  jest.clearAllMocks();
  mockedFs.readFileSync.mockReset();
});

/** Small helper: program readFileSync to return per-path content. */
function mockReads(map: Record<string, string | Error>): void {
  mockedFs.readFileSync.mockImplementation((p: fs.PathOrFileDescriptor) => {
    const key = String(p);
    const found = Object.entries(map).find(([k]) => key.endsWith(k));
    if (!found) {
      const err = new Error("ENOENT") as NodeJS.ErrnoException;
      err.code = "ENOENT";
      throw err;
    }
    if (found[1] instanceof Error) throw found[1];
    return found[1];
  });
}

describe("StateReader — JSON state files", () => {
  it("activeFeature returns parsed payload", () => {
    mockReads({
      "active_feature.json": JSON.stringify({
        feature: "auth-flow",
        per_repo_paths: { api: "/ws/api", ui: "/ws/ui" },
      }),
    });
    const r = new StateReader("/ws", 1000);
    const af = r.activeFeature();
    expect(af?.feature).toBe("auth-flow");
    expect(af?.per_repo_paths).toEqual({ api: "/ws/api", ui: "/ws/ui" });
  });

  it("activeFeature returns null when the file is missing", () => {
    mockReads({});
    const r = new StateReader("/ws");
    expect(r.activeFeature()).toBeNull();
  });

  it("malformed JSON is treated as missing (returns null) — not a crash", () => {
    mockReads({ "active_feature.json": "{ not valid json" });
    const r = new StateReader("/ws");
    expect(r.activeFeature()).toBeNull();
  });

  it("heads returns {} when file missing (not null) for ergonomic iteration", () => {
    mockReads({});
    const r = new StateReader("/ws");
    expect(r.heads()).toEqual({});
  });

  it("preflight returns {} when file missing", () => {
    mockReads({});
    expect(new StateReader("/ws").preflight()).toEqual({});
  });

  it("features returns {} when file missing", () => {
    mockReads({});
    expect(new StateReader("/ws").features()).toEqual({});
  });

  it("features parses real entries (per-repo branches map preserved)", () => {
    mockReads({
      "features.json": JSON.stringify({
        "doc-1003": {
          repos: ["api", "ui"],
          status: "active",
          branches: { api: "doc-1003-fixes", ui: "DOC-1003-fixes-v2" },
        },
      }),
    });
    const f = new StateReader("/ws").features();
    expect(f["doc-1003"].branches).toEqual({
      api: "doc-1003-fixes",
      ui: "DOC-1003-fixes-v2",
    });
  });
});

describe("StateReader — caching", () => {
  it("caches reads within the TTL", () => {
    mockReads({ "heads.json": JSON.stringify({ api: { branch: "main", sha: "abc" } }) });
    const r = new StateReader("/ws", 60_000);
    r.heads();
    r.heads();
    r.heads();
    // 1 read each for the canopy_toml fallback + heads → just heads here.
    expect(mockedFs.readFileSync).toHaveBeenCalledTimes(1);
  });

  it("invalidate(key) drops just that key's cache", () => {
    mockReads({
      "heads.json": JSON.stringify({ api: { branch: "main", sha: "abc" } }),
      "active_feature.json": JSON.stringify({ feature: "x" }),
    });
    const r = new StateReader("/ws", 60_000);
    r.heads();
    r.activeFeature();
    expect(mockedFs.readFileSync).toHaveBeenCalledTimes(2);
    r.invalidate("heads");
    r.heads();        // re-read
    r.activeFeature(); // still cached
    expect(mockedFs.readFileSync).toHaveBeenCalledTimes(3);
  });

  it("invalidateAll() drops every cached entry", () => {
    mockReads({
      "heads.json": "{}",
      "active_feature.json": "{}",
    });
    const r = new StateReader("/ws", 60_000);
    r.heads();
    r.activeFeature();
    r.invalidateAll();
    r.heads();
    r.activeFeature();
    expect(mockedFs.readFileSync).toHaveBeenCalledTimes(4);
  });
});

describe("parseCanopyTomlMinimal", () => {
  it("extracts workspace name + repo names + tracker", () => {
    const toml = `
[workspace]
name = "demo-product"

[[repos]]
name = "api"
path = "./api"

[[repos]]
name = "ui"
path = "./ui"

[issue_provider]
name = "github_issues"
`;
    expect(parseCanopyTomlMinimal(toml)).toEqual({
      workspace_name: "demo-product",
      repo_names: ["api", "ui"],
      tracker_type: "github_issues",
      repo_labels: {},
    });
  });

  it("captures per-repo label mappings when present", () => {
    const toml = `
[workspace]
name = "x"

[[repos]]
name = "api"
path = "./api"
label = "backend"

[[repos]]
name = "ui"
path = "./ui"
label = "frontend"
`;
    const out = parseCanopyTomlMinimal(toml);
    expect(out.repo_labels).toEqual({ api: "backend", ui: "frontend" });
  });

  it("ignores TOML comments + blank lines", () => {
    const toml = `
# top-level comment
[workspace]
# inline section comment
name = "demo"  # trailing comment

[[repos]]
name = "api"
`;
    const out = parseCanopyTomlMinimal(toml);
    expect(out.workspace_name).toBe("demo");
    expect(out.repo_names).toEqual(["api"]);
  });

  it("returns empty defaults on empty input", () => {
    expect(parseCanopyTomlMinimal("")).toEqual({
      workspace_name: "",
      repo_names: [],
      tracker_type: "",
      repo_labels: {},
    });
  });

  it("ignores sections we don't care about (augments, sub-tables)", () => {
    const toml = `
[workspace]
name = "x"

[augments]
preflight_cmd = "make check"

[issue_provider]
name = "linear"

[issue_provider.linear]
api_key_env = "LINEAR_API_KEY"

[[repos]]
name = "api"
path = "./api"
`;
    const out = parseCanopyTomlMinimal(toml);
    expect(out.workspace_name).toBe("x");
    expect(out.tracker_type).toBe("linear");
    expect(out.repo_names).toEqual(["api"]);
    // augments + sub-tables intentionally not surfaced — CLI handles those.
  });

  it("supports single-quoted strings", () => {
    const toml = `
[workspace]
name = 'single-quoted'
`;
    expect(parseCanopyTomlMinimal(toml).workspace_name).toBe("single-quoted");
  });
});

describe("StateReader.canopyToml convenience accessors", () => {
  const toml = `
[workspace]
name = "demo"

[[repos]]
name = "api"
label = "backend"

[[repos]]
name = "ui"

[issue_provider]
name = "github_issues"
`;
  it("workspaceName / repoNames / trackerType / hasIssueTracker", () => {
    mockReads({ "canopy.toml": toml });
    const r = new StateReader("/ws");
    expect(r.workspaceName()).toBe("demo");
    expect(r.repoNames()).toEqual(["api", "ui"]);
    expect(r.trackerType()).toBe("github_issues");
    expect(r.hasIssueTracker()).toBe(true);
  });

  it("hasIssueTracker is false when block missing", () => {
    mockReads({
      "canopy.toml": `[workspace]\nname = "x"\n\n[[repos]]\nname = "api"\n`,
    });
    expect(new StateReader("/ws").hasIssueTracker()).toBe(false);
  });
});

import {
  CanopyBlockerError,
  CanopyCli,
  isBlocker,
  parseCanopyJson,
} from "./canopyCli";

jest.mock("node:child_process", () => ({
  execFile: jest.fn(),
}));

const { execFile } = jest.requireMock("node:child_process") as {
  execFile: jest.Mock;
};

beforeEach(() => {
  execFile.mockReset();
});

/**
 * Helper: program execFile to return `stdout`/`stderr` and the given exit
 * code. The Node `execFile(file, args, opts, cb)` signature passes
 * `(err, stdout, stderr)`; non-zero exit codes manifest as `err.code`.
 */
function mockExecFile(opts: {
  stdout?: string;
  stderr?: string;
  exitCode?: number;
  errType?: "ENOENT" | "TIMEOUT";
}): void {
  execFile.mockImplementation((_file, _args, _execOpts, cb) => {
    if (opts.errType === "ENOENT") {
      const err = new Error("not found") as NodeJS.ErrnoException;
      err.code = "ENOENT";
      return cb(err, "", "");
    }
    if (opts.errType === "TIMEOUT") {
      const err = new Error("timed out") as Error & { killed?: boolean };
      err.killed = true;
      return cb(err, opts.stdout ?? "", opts.stderr ?? "");
    }
    if (opts.exitCode && opts.exitCode !== 0) {
      const err = new Error("nonzero") as Error & { code?: number };
      err.code = opts.exitCode;
      return cb(err, opts.stdout ?? "", opts.stderr ?? "");
    }
    cb(null, opts.stdout ?? "", opts.stderr ?? "");
  });
}

describe("parseCanopyJson", () => {
  it("parses a clean JSON object", () => {
    expect(parseCanopyJson('{"feature":"x","state":"no_prs"}')).toEqual({
      feature: "x",
      state: "no_prs",
    });
  });

  it("parses a clean JSON array", () => {
    expect(parseCanopyJson("[1,2,3]")).toEqual([1, 2, 3]);
  });

  it("strips Rich console output before the JSON", () => {
    const out = parseCanopyJson('Spinner …\n  Working on it\n{"feature":"x"}\n');
    expect(out).toEqual({ feature: "x" });
  });

  it("throws on empty stdout", () => {
    expect(() => parseCanopyJson("")).toThrow(/empty stdout/);
  });

  it("throws when no { or [ is present", () => {
    expect(() => parseCanopyJson("just some text")).toThrow(/no JSON payload/);
  });
});

describe("isBlocker", () => {
  it("recognises a typical blocker shape", () => {
    expect(isBlocker({ status: "blocked", code: "x", what: "y" })).toBe(true);
    expect(isBlocker({ status: "failed", code: "x", what: "y" })).toBe(true);
  });

  it("rejects normal success payloads", () => {
    expect(isBlocker({ feature: "x", state: "no_prs" })).toBe(false);
  });

  it("rejects partial / wrong-shape payloads", () => {
    expect(isBlocker(null)).toBe(false);
    expect(isBlocker("blocked")).toBe(false);
    expect(isBlocker({ status: "blocked" })).toBe(false);
    expect(isBlocker({ code: "x", what: "y" })).toBe(false);
  });
});

describe("CanopyCli.exec", () => {
  let cli: CanopyCli;
  beforeEach(() => {
    cli = new CanopyCli("/usr/local/bin/canopy", "/ws");
    // Stub the login-shell call to avoid executing a real shell during tests.
    // The first .exec() triggers it; subsequent calls reuse the cached PATH.
    (cli as unknown as { resolvedShellPath: string }).resolvedShellPath = "/stub/PATH";
  });

  it("returns the parsed JSON on success", async () => {
    mockExecFile({ stdout: '{"feature":"x"}' });
    const out = await cli.exec(["state", "x", "--json"]);
    expect(out).toEqual({ feature: "x" });
  });

  it("throws CanopyBlockerError on a structured blocker payload", async () => {
    mockExecFile({
      exitCode: 1,
      stdout: JSON.stringify({
        status: "blocked",
        code: "no_upstream",
        what: "no upstream",
        fix_actions: [{ action: "push", args: { set_upstream: true }, safe: false }],
      }),
    });
    await expect(cli.exec(["push", "--json"])).rejects.toMatchObject({
      name: "CanopyBlockerError",
      code: "no_upstream",
      fix_actions: expect.any(Array),
    });
  });

  it("CanopyBlockerError exposes structured fields", async () => {
    mockExecFile({
      exitCode: 1,
      stdout: JSON.stringify({
        status: "blocked",
        code: "wrong_branch",
        what: "drift detected",
        details: { per_repo: { api: { expected: "feat", actual: "main" } } },
      }),
    });
    try {
      await cli.exec(["commit", "-m", "x", "--json"]);
      throw new Error("should have thrown");
    } catch (e) {
      const err = e as CanopyBlockerError;
      expect(err).toBeInstanceOf(CanopyBlockerError);
      expect(err.code).toBe("wrong_branch");
      expect(err.details).toEqual({
        per_repo: { api: { expected: "feat", actual: "main" } },
      });
    }
  });

  it("throws a 'CLI not found' error on ENOENT", async () => {
    mockExecFile({ errType: "ENOENT" });
    await expect(cli.exec(["state", "--json"])).rejects.toThrow(/canopy CLI not found/);
  });

  it("throws a timeout error when the subprocess is killed", async () => {
    mockExecFile({ errType: "TIMEOUT" });
    await expect(cli.exec(["state", "--json"], { timeoutMs: 100 })).rejects.toThrow(
      /timed out after 100ms/,
    );
  });

  it("surfaces stderr when exit is non-zero with no JSON in stdout", async () => {
    mockExecFile({ exitCode: 2, stderr: "boom: real error" });
    await expect(cli.exec(["bad-cmd", "--json"])).rejects.toThrow(/boom: real error/);
  });

  it("caches successful results within the TTL window", async () => {
    mockExecFile({ stdout: '{"feature":"x","ver":1}' });
    const a = await cli.exec(["state", "--json"], { cacheTtlMs: 30_000 });
    // Re-program execFile so a cache miss would be visibly different.
    mockExecFile({ stdout: '{"feature":"x","ver":2}' });
    const b = await cli.exec(["state", "--json"], { cacheTtlMs: 30_000 });
    expect(a).toEqual({ feature: "x", ver: 1 });
    expect(b).toEqual(a);   // cache hit
    expect(execFile).toHaveBeenCalledTimes(1);
  });

  it("does not cache when cacheTtlMs is omitted (write path)", async () => {
    mockExecFile({ stdout: '{"feature":"x","ver":1}' });
    await cli.exec(["state", "--json"]);
    mockExecFile({ stdout: '{"feature":"x","ver":2}' });
    const b = await cli.exec(["state", "--json"]);
    expect(b).toEqual({ feature: "x", ver: 2 });
    expect(execFile).toHaveBeenCalledTimes(2);
  });

  it("invalidateCache clears stored entries", async () => {
    mockExecFile({ stdout: '{"feature":"x","ver":1}' });
    await cli.exec(["state", "--json"], { cacheTtlMs: 30_000 });
    cli.invalidateCache();
    mockExecFile({ stdout: '{"feature":"x","ver":2}' });
    const b = await cli.exec(["state", "--json"], { cacheTtlMs: 30_000 });
    expect(b).toEqual({ feature: "x", ver: 2 });
    expect(execFile).toHaveBeenCalledTimes(2);
  });
});

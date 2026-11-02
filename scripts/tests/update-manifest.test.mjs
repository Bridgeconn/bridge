import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { writeUpdateManifest } from "../write-update-manifest.mjs";

test("the feed references the exact signed installer and refuses unsigned or mismatched releases", async () => {
  const dir = await mkdtemp(join(tmpdir(), "bridge-update-manifest-"));
  try {
    const args = { repository: "Bridgeconn/bridge", tag: "v1.2.3", version: "1.2.3", installer: join(dir, "Bridge_1.2.3_x64-setup.exe"), output: join(dir, "latest.json") };
    await assert.rejects(writeUpdateManifest(args));
    await writeFile(`${args.installer}.sig`, "signed installer bytes\n", "utf8");
    const manifest = await writeUpdateManifest(args);
    assert.equal(manifest.platforms["windows-x86_64"].signature, "signed installer bytes");
    assert.equal(manifest.platforms["windows-x86_64"].url, "https://github.com/Bridgeconn/bridge/releases/download/v1.2.3/Bridge_1.2.3_x64-setup.exe");
    assert.deepEqual(JSON.parse(await readFile(args.output, "utf8")), manifest);
    await assert.rejects(writeUpdateManifest({ ...args, tag: "v1.2.4" }), /matching/);
    await assert.rejects(writeUpdateManifest({ ...args, version: "1.2.3-beta.1", tag: "v1.2.3-beta.1" }), /stable/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
